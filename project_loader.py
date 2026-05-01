"""Build a Project from a YAML config file.

Schema (see example.yaml):

    project:
      work_dir: <path>         # required
      output_dir: <path>       # required
      fonts_dir: <path>        # required
      profile: <str>           # required, name of a class in `constants` (e.g. "UBP_X700")
      hdr: <bool>              # optional, default False
      hardsub: <bool>          # optional, default False
      encode_aud: <bool>       # optional
      target_size: <str>       # optional, name of a constants attr (e.g. "BD_SIZE", "BD_DL_SIZE")
      cropstring: <str>        # optional
      scalestring: <str>       # optional
      videotune: <str>         # optional

    sources:                   # optional; if omitted a default source is auto-created
      - name: <str>

    episodes:
      - ep_num: <int>          # required
        vid_src: <path>        # required
        name: <str>            # optional
        source: <str>          # optional, must match a name under `sources:`
        aud_track: <int>       # optional, default 0
        sub_track: <int>       # optional, default 0
        aud_src: <path>        # optional
        sub_src: <path>        # optional

Project-level settings not covered above stay at the Project class defaults.
"""

import inspect
from pathlib import Path

import yaml

import constants
from episode import Episode
from project import Project


def _resolve_profile(name):
    profile = getattr(constants, name, None)
    if profile is None:
        raise ValueError(f"Unknown profile '{name}' (no such attribute in constants.py)")
    return profile


def _resolve_target_size(name):
    resolved = getattr(constants, name, None)
    if resolved is None:
        raise ValueError(f"Unknown target_size constant '{name}'")
    return resolved


def build_project_from_yaml(yaml_path, ui_manager=None):
    """Parse `yaml_path` and return a configured (but un-processed) Project."""
    yaml_path = Path(yaml_path)

    # Validate file extension
    if yaml_path.suffix.lower() not in ('.yaml', '.yml'):
        raise ValueError(f"{yaml_path}: not a YAML file (expected .yaml or .yml extension)")

    with yaml_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError(f"{yaml_path}: top-level YAML must be a mapping")

    proj_cfg = config.get("project")
    if not proj_cfg:
        raise ValueError(f"{yaml_path}: missing required 'project' section")

    episodes_cfg = config.get("episodes") or []
    if not isinstance(episodes_cfg, list):
        raise ValueError(f"{yaml_path}: 'episodes' must be a list")

    sources_cfg = config.get("sources") or []
    if not isinstance(sources_cfg, list):
        raise ValueError(f"{yaml_path}: 'sources' must be a list")

    # --- Project-level setup (mirrors setup_and_run_project) ---
    # Use the YAML filename (without extension) as the project name.
    name = yaml_path.stem
    proj = Project.load_or_build(name, ui_manager=ui_manager)

    proj.set_work_dir(proj_cfg["work_dir"])
    proj.set_output_dir(proj_cfg["output_dir"])
    proj.set_fonts_dir(proj_cfg["fonts_dir"])
    proj.profile = _resolve_profile(proj_cfg["profile"])

    if "target_size" in proj_cfg:
        proj.TARGET_SIZE = _resolve_target_size(proj_cfg["target_size"])
    if "hdr" in proj_cfg:
        proj.hdr = bool(proj_cfg["hdr"])
    if "hardsub" in proj_cfg:
        proj.hardsub_all = bool(proj_cfg["hardsub"])
    if "encode_aud" in proj_cfg:
        proj.encode_aud = bool(proj_cfg["encode_aud"])
    if "cropstring" in proj_cfg:
        proj.cropstring = proj_cfg["cropstring"]
    if "scalestring" in proj_cfg:
        proj.scalestring = proj_cfg["scalestring"]
    if "videotune" in proj_cfg:
        proj.videotune = proj_cfg["videotune"]

    # --- Sources ---
    for src in sources_cfg:
        proj.add_source(src["name"])

    # --- Episodes ---
    # Build Episode instances directly from each YAML entry and hand them to
    # the project. The accepted keys are derived from Episode.__init__'s
    # signature so adding a new field to Episode is picked up here
    # automatically — no Project.add_episode passthrough to keep in sync.
    ep_params = set(inspect.signature(Episode.__init__).parameters)
    # Handled explicitly below / already required positional args.
    reserved = {"self", "ep_num", "vid_src", "origin_src"}
    yaml_only = {"source"}  # YAML aliases that map to a different ctor kwarg
    for ep in episodes_cfg:
        unknown = set(ep) - ep_params - yaml_only - {"ep_num", "vid_src"}
        if unknown:
            raise ValueError(
                f"{yaml_path}: episode {ep.get('ep_num')!r} has unknown keys: {sorted(unknown)}"
            )
        kwargs = {k: v for k, v in ep.items() if k in ep_params and k not in reserved}
        origin_src = proj.get_source(ep["source"]) if "source" in ep else None
        episode = Episode(ep["ep_num"], origin_src, ep["vid_src"], **kwargs)
        proj.add_episode(episode)

    return proj
