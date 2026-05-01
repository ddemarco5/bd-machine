import sys
from project_loader import build_project_from_yaml
from ui import UIManager
from ui_redirector import PrintRedirector


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config.yaml>", file=sys.stderr)
        sys.exit(2)
    crf_hint = None
    if len(sys.argv) == 3:
        crf_hint = sys.argv[2]
    config_path = sys.argv[1]
        

    exit_code = 0
    with UIManager() as ui:
        # Start redirector immediately so ALL prints go to UI scrollback.
        redirector = PrintRedirector(ui)
        redirector.start()
        try:
            ui.update_status("Initializing...")
            try:
                proj = build_project_from_yaml(config_path, ui_manager=ui)
                if crf_hint is not None:
                    print(f"Recieved CRF hint of {crf_hint} from CLI")
                    proj.process_project(crf_hint=int(crf_hint))
                else:
                    proj.process_project()
            except KeyboardInterrupt:
                # Surface the interrupt in the UI while it's still alive,
                # then exit with the conventional SIGINT code.
                ui.update_status("Handling Ctrl-C — shutting down...")
                ui.log("Interrupted by user (Ctrl-C). Exiting cleanly.")
                exit_code = 130
        finally:
            redirector.stop()

    sys.exit(exit_code)