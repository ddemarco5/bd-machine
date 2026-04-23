import sys
from project import Project
import constants
from ui import UIManager
from ui_redirector import PrintRedirector


def setup_and_run_project(ui):
    """Setup and run the project using the provided UI manager."""
    # Load or build project
    proj = Project.load_or_build("Sisu", ui_manager=ui)

    proj.set_work_dir("workspace")
    proj.set_output_dir("encoded")
    proj.set_fonts_dir("fonts")
    proj.profile = constants.UBP_X700

    # proj.encode_aud = True
    proj.hdr = True
    # proj.hardsub = True

    # proj.cropstring = "3840:1920:0:120"
    # proj.scalestring = "1920:-1"

    proj.add_episode(1,
        vid_src=("Z:/Movies/Sisu (2022)/Sisu (2022) {imdb-tt14846026} [Remux-2160p Proper][DV HDR10][TrueHD Atmos 7.1][HEVC]-CiNEPHiLES.mkv"),
        aud_track=1,
        sub_track=4,
        name="Sisu",
    )


    # Process project
    proj.process_project(crf_hint=17)


if __name__ == "__main__":
    exit_code = 0
    with UIManager() as ui:
        # Start redirector immediately so ALL prints go to UI scrollback.
        redirector = PrintRedirector(ui)
        redirector.start()
        try:
            ui.update_status("Initializing...")
            try:
                setup_and_run_project(ui)
            except KeyboardInterrupt:
                # Surface the interrupt in the UI while it's still alive,
                # then exit with the conventional SIGINT code.
                ui.update_status("Handling Ctrl-C — shutting down...")
                ui.log("Interrupted by user (Ctrl-C). Exiting cleanly.")
                exit_code = 130
        finally:
            redirector.stop()

    sys.exit(exit_code)