import os
from pathlib import Path

import constants
from ui import UIManager
from ui_redirector import FFmpegOutputHandler


def _run(command, ui_manager: UIManager, episode_duration_ms: float = 0) -> int:
    """Run `command` via FFmpegOutputHandler, streaming output to the UI."""
    str_command = [str(c) for c in command]
    handler = FFmpegOutputHandler(ui_manager, episode_duration_ms=episode_duration_ms)
    return handler.run_command(str_command, shell=False)

def encode_audio(episode, out_path, profile, ui_manager: UIManager) -> None:
    filename = "aud" + str(episode.ep_num) + ".mkv"
    
    command = ["ffmpeg", "-y",
               "-v", "quiet",
               #"-hide_banner",
               "-stats",
               "-i", episode.aud_src.absolute(), 
               "-c:a", profile.audio_codec, 
               #"-b:a", profile.audio_bitrate, 
               "-q:a", profile.audio_qual,
               "-ac", "2", 
               "-map", "a:" + str(episode.aud_track),
               "-map_metadata", "-1",
               (out_path / filename).absolute()]
    if _run(command, ui_manager) != 0:
        return None
    # ffmpeg aac bug, stream size isn't correctly written to output file.
    # we need to run mkvpropedit to manually correct this.
    # This is safe to do blindly because the tool is included with mkvtoolsnix
    command = ["mkvpropedit",
               (out_path / filename).absolute(),
               "--add-track-statistics-tags"]
    if _run(command, ui_manager) != 0:
        return None
    return out_path / filename

def extract_elementary_dts_audio(episode, out_path, profile, ui_manager: UIManager) -> None:
    filename = "aud" + str(episode.ep_num) + ".dts"
    
    command = ["ffmpeg", "-y",     
               "-v", "quiet",
               "-stats",
               "-i", episode.aud_src.absolute(),
               "-map", "a:" + str(episode.aud_track),
               "-c:a", "copy", 
               "-bsf:a", "dca_core",
               (out_path / filename).absolute()]
    if _run(command, ui_manager) != 0:
        return None
    return out_path / filename

def encode_video(episode, out_path, profile, crf, hardsub_all, fontsdir, ui_manager: UIManager, start_time=None, stop_time=None, cropstring=None, scalestring=None, videotune=None, keephdr=False) -> None:
  
    filename = "vid" + str(episode.ep_num)
    if keephdr:
        # TODO: for dolby vision this will need to be changed to ts or mp4 (depending on audio)
        filename += ".mkv"
    else:
        filename += ".mkv"
    
    # build the level-setting string based on the encoder chosen
    if profile.video_codec == "libx264" or \
       profile.video_codec == "hevc_nvenc":
        level = ["-level", profile.video_level]
    elif profile.video_codec == "libx265":
        # TODO: these levels are hardcoded for 5.1, put some logic in to adjust accordingly
        level = ["-x265-params", f"level-idc={profile.video_level}:vbv-bufsize=160000:vbv-maxrate=160000"]
        if keephdr:
            level[-1] = level[-1] + ":hdr-opt=1"
    else:
        print("don't know how to set the level for specified encoder, exiting")
        exit(1)
        
    # Choose the correct hwinit args
    gpustring = "vulkan=vk0"
    if os.name != "nt":
        # This is a fix for the intel vulkan mesa drivers not playing nice with multiplane
        gpustring += ",disable_multiplane=1"
    
    if profile.video_codec == "hevc_nvenc":
        # NVENC -cq is 8.8 fixed-point but the driver only honors the top 2 bits
        # of the fractional byte (see constants.NVENC_CQ_STEP). Quantize here so
        # every caller passes a value the encoder can actually act on.
        crf = round(crf / constants.NVENC_CQ_STEP) * constants.NVENC_CQ_STEP
        command = ["ffmpeg", "-y",      
                "-v", "quiet",
                "-hide_banner",
                "-stats",
                "-i", episode.vid_src.absolute(),
                "-c:v", profile.video_codec,
                # "-pix_fmt", profile.pixel_format,
                *level,
                "-rc", "vbr",
                "-cq", str(crf),
                "-preset", "p7",
                "-tune", "hq",
                "-spatial-aq", "1",
                "-temporal-aq", "1",
                "-b_ref_mode", "2",
                "-bufsize", "160M",
                "-profile:v", "main10",
                "-tier", "main",
                "-rc-lookahead", "40",
                "-lookahead_level", "3",
                "-map", "v:" + str(episode.vid_track),
                "-map_metadata", "-1",
                    (out_path / filename).absolute()]
    else:
        command = ["ffmpeg", "-y",
                "-v", "quiet",
                "-hide_banner",
                "-init_hw_device", gpustring,
                "-stats",
                "-i", episode.vid_src.absolute(),
                "-c:v", profile.video_codec,
                "-pix_fmt", profile.pixel_format,
                *level,
                "-crf", str(crf),
                #    "-preset", "veryslow",
                "-preset", "slow",
                #"-tune", "animation",
                "-map", "v:" + str(episode.vid_track),
                "-map_metadata", "-1",
                    (out_path / filename).absolute()]
    
    vid_filter_string = ""
    if episode.interlaced:
        print("Interlaced episode detected, deinterlacing")
        vid_filter_string = "yadif=mode=0:parity=-1:deint=all,"
        
    if cropstring:
        print(f"Cropstring detected: {cropstring}")
        vid_filter_string += f"crop={cropstring},"   
            
    if scalestring:
        print(f"Scalestring detected: {scalestring}")
        vid_filter_string += f"scale={scalestring},"

    if ((hardsub_all and episode.sub_enc) or 
        episode.hardsub_enc):
        if hardsub_all:
            print("Adding global hardsub")
            sub_source = episode.sub_enc
        else:
            print("Adding local hardsub")
            sub_source = episode.hardsub_enc
        subpath = sub_source.absolute()
        fontpath = fontsdir.absolute()
        if os.name == "nt":
            print("Running in windows, fixing paths for the ffmpeg hardsub filter")
            # stupid hack we have to do in order to double escape our windows path for the subtitles filter
            # https://trac.ffmpeg.org/ticket/3334
            # https://superuser.com/questions/1247197/ffmpeg-absolute-path-error
            # to get it to work with subprocess I need to convert it to a posix style path and strip off C:
            # ALSO, special characters like [ in the filename will break it too. Pain in the ass
            subpath = sub_source.absolute().as_posix()[2:]
            fontpath = fontsdir.absolute().as_posix()[2:]
        vid_filter_string += f"subtitles=filename={str(subpath)}:fontsdir={str(fontpath)},"

    if episode.hdr and not keephdr:
        print("HDR detected, using libplacebo to convert to SDR")
        vid_filter_string += f"hwupload,libplacebo=tonemapping=auto:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=limited:deband=true:gamut_mode=desaturate:format={profile.pixel_format},hwdownload,format={profile.pixel_format},"

    elif episode.hdr and keephdr:
        print("HDR source detected and our target video will also be hdr")

        
    if vid_filter_string != "":
        filter_cmd = ["-vf", vid_filter_string]
        #print(f"Video filter built: {filter_cmd}")
        command = command[:-3] + filter_cmd + command[-3:]
        #command.insert(-3, filter_cmd)
    
    # Add the rate if it's specificed in the episode
    if episode.framerate:
        print("adding framerate " + episode.framerate)
        command = command[:-1] + ["-r", episode.framerate] + command[-1:]
        
    # Add a start time if specified
    if start_time and episode.duration_src:
        print(f"adding a start time of {start_time}")
        command = command[:10] + ["-ss", str(start_time)] + command[10:]
        # print(command)
        # exit()
        
    # Add a stop time if our video duration exceeds what is specified
    if stop_time and episode.duration_src:
        print("adding a stop time of " + stop_time)
        command = command[:-1] + ["-t", stop_time] + command[-1:]
        
    # Add a video tune option if provided
    if videotune:
        print(f"adding a video tune option of '{videotune}'")
        command = command[:-1] + ["-tune", videotune] + command[-1:]
        
    # Add option to allow our mp4 to be hdr/dv compliant
    if keephdr:
        print(f"enabling '-strict unofficial' to keep hdr")
        command = command[:-1] + ["-strict", "unofficial"] + command[-1:]
    
    # print("about to run command:")
    # print(command)
    # exit()
    
    result = _run(command, ui_manager, episode_duration_ms=episode.duration_src)
    if result != 0:
        print(f"non-zero retcode for encode: {result}")
        exit(result)
    return out_path / filename

def mkv_extract(infile, content, output_path, track_ids, track_names, ui_manager: UIManager):
    if len(track_ids) is not len(track_names):
        print("Error, track_ids is not the same len as track_names")
        print(track_ids)
        print(track_names)
        exit(1)
    command = [
        "mkvextract",
        infile.absolute(),
        content
    ]
    for i in range(0, len(track_ids)):
        command.append(str(track_ids[i]) + ":" + str((output_path / track_names[i]).absolute()))
        
    # print(command)
    # exit()
    
    result = _run(command, ui_manager)
    if result != 0:
        print(f"non-zero retcode for extract: {result}")
        exit(result)

def extract_sub_track(src, track, out_path, filename, ui_manager: UIManager, convert_to_srt=True, sub_format=None):
    if src.suffix.lower() == ".srt":
        return src
    fmt = (sub_format or "").lower()
    if fmt in ("pgs", "vobsub", "hdmv"):
        print(f"Cannot convert bitmap subtitles ({fmt}) to SRT")
        exit(1)
    # Timed Text / tx3g isn't a usable sidecar, always convert
    if convert_to_srt or fmt in ("timed text", "tx3g"):
        filename = filename + ".srt"
        codec = "srt"
    else:
        if fmt in ("utf-8", "srt"):
            fmt = "srt"
        filename = filename + "." + (fmt if fmt else "sub")
        codec = "copy"
    outfile = out_path / filename
    command = ["ffmpeg", "-y",
               "-v", "quiet",
               "-stats",
               "-i", src.absolute(),
               "-map", "0:s:" + str(track),
               "-c:s", codec,
               outfile.absolute()]
    result = _run(command, ui_manager)
    if result != 0:
        print(f"non-zero retcode for subtitle extract: {result}")
        print(f"Cannot convert subtitles of type {fmt or 'unknown'} to SRT")
        exit(result)
    return outfile

def mux_mkv(episode, out_path, ui_manager: UIManager, hardsub_global=False) -> None:
    # We want 2 digts for our episode number string unless we need more
    if episode.ep_num <= 99:
        ep_num_str = "{:02d}".format(int(episode.ep_num))
    else:
        ep_num_str = str(episode.ep_num)
    outfile = out_path / (ep_num_str + " - " + episode.ep_name + ".mkv")
    
    #aud_track = episode.audio_info.audio_tracks[episode.aud_track].streamorder
    # aud_track = episode.audio_info.audio_tracks[episode.aud_track].stream_identifier
    vid_track = str(episode.get_vid_tracknum_absolute())
    aud_track = str(episode.get_aud_tracknum_absolute())
    if os.name == "nt":
        lang = "en"
    else:
        lang = "en_US"
    command = [
        "mkvmerge",
        "--ui-language", lang,
        "--output", str(outfile),
        "--video-tracks", vid_track,
        "--no-track-tags", "--no-global-tags",
        "--track-name", "0:",
        "--no-audio", "--no-subtitles",  "--no-attachments",
        "--language", "0:und",
        "(", episode.vid_enc.absolute(), ")", # video track
        "--audio-tracks", aud_track,
        "--no-track-tags", "--no-global-tags",
        "--track-name", f"{aud_track}:",
        "--no-video", "--no-subtitles", "--no-chapters", "--no-attachments",
        "--language", f"{aud_track}:eng", # audio track
        "(", episode.aud_enc.absolute(), ")",
    ]
    
    track_order = ["--track-order", f"0:0,1:{aud_track}"]
    # If we aren't hardsubbing the episode (either project-wide via
    # hardsub_global or per-episode via hardsub_enc), include the sub track.
    if not (hardsub_global and episode.sub_enc) or episode.hardsub_enc:
        sub_track = str(episode.get_sub_tracknum_absolute())
        command = command + ["--no-video", "--no-audio", "--no-chapters", "--no-track-tags", "--no-global-tags","--no-attachments"]
        command = command + ["--subtitle-tracks", sub_track]
        command = command + ["--language", "0:eng"]
        command = command + ["--track-name", f"{sub_track}:"]
        command = command + ["(", episode.sub_enc.absolute(), ")"]
        track_order[1] = track_order[1] + f",2:{sub_track}"
    
    # Append the track orders
    command = command + track_order
    
    # Debug
    # print(command)
    # exit()
    
    result = _run(command, ui_manager)
    if result != 0:
        print(f"non-zero retcode for mux: {result}")
        exit(result)
    return outfile