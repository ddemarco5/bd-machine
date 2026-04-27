import math
import os
import sys
import pickle
from pymediainfo import MediaInfo

from pathlib import Path

import numpy
from scipy.optimize import root_scalar

from enum import Enum, auto

import constants
from commands import *
from episode import Episode
from models import Model,ModelType
from source import Source
from ui import UIManager


class Project:
    class state(Enum):
        NEW = auto()
        SCANNING = auto()
        AUDIO = auto()
        SUBS = auto()
        PROFILE = auto()
        PROCESSING = auto()
        DONE = auto()
    def __init__(self, name="project", ui_manager=None):
        self.name = name
        self.ui = ui_manager
        self.project_state = self.state.NEW 
        self.workdir = None
        self.outputdir = None
        
        self.sources = []
        
        self.episodes = []
        self.total_duration = 0
        self.total_sub_size = 0
        self.total_audio_size = 0
        self.total_video_size = 0
        self.total_project_size = 0
        
        # self.profile = constants.BDP_S3700
        self.profile = constants.UBP_X700
        self.TARGET_SIZE = constants.BD_SIZE
        
        # Project options
        self.hardsub = False
        self.encode_aud = False
        self.hdr = False
        self.fonts_dir = False
        self.cropstring = None
        self.scalestring = None
        self.videotune = None
        
        # Project state variables
        self.current_crf = None
        self.last_attempted_crf = None
        self.eps_to_process = None
        self.last_percent_off = None
        self.num_iterations = 0
        
        # The fine-tune linear model
        self.fine_tune_model = Model(ModelType.LINEAR, maxsize=4)

        # Size-error history (fractional percent_off per encode pass).
        # Persisted across pause/resume so the UI History bar survives reloads.
        self.size_history = []

    # Pickle stuff
    def __reduce__(self):
        # Return a tuple of the callable and the arguments to recreate the object
        # Exclude 'ui' from pickled state - it gets re-injected on load
        state = {k: v for k, v in self.__dict__.items() if k != 'ui'}
        return (self.__class__, (), state)

    def __setstate__(self, state):
        # Restore the instance's state from the state dictionary
        self.__dict__.update(state)

    @classmethod
    def load_or_build(cls, filename, ui_manager=None):
        pickle_file = f"{filename}.pkl"
        # Load the class from a file
        if os.path.exists(pickle_file):
            msg = f"Loading project from {pickle_file}"
            print(msg)
            with open(pickle_file, "rb") as f:
                instance = pickle.load(f)
            # Inject the UI manager into loaded instance
            instance.ui = ui_manager
            # Replay persisted size-error history into the UI's History bar.
            if ui_manager is not None:
                ui_manager.set_history(instance.size_history)
            return instance
        else:
            msg = f"{pickle_file} wasn't found, creating a new project"
            print(msg)
            return cls(filename, ui_manager=ui_manager)
        
    def save(self):
        print("Saving project to file")
        with open(f"{self.name}.pkl", "wb") as f:
            pickle.dump(self, f)
            
    def set_work_dir(self, workdir):
        self.workdir = Path(workdir)
        if not self.workdir.exists():
            print("Defined workspace directory doesn't exist. Creating...")
            Path.mkdir(self.workdir)
            
    def set_output_dir(self, outdir):
        self.outputdir = Path(outdir)
        if not self.outputdir.exists():
            print("Defined output directory doesn't exist. Creating...")
            Path.mkdir(self.outputdir)
            
    def set_fonts_dir(self, fontdir):
        # font dir cannot be the same as workdir due to an ffmpeg interaction
        self.fonts_dir = Path(fontdir)
        if self.fonts_dir == self.workdir:
            print("Fonts directory and workspace directory cannot be identical")
            exit(1)
        if not self.outputdir.exists():
            print("Defined fonts directory doesn't exist. Creating...")
            Path.mkdir(self.outputdir)
        
    def set_all_audio_tracks(self, tracknum):
        print(f"Setting all audio tracks to {tracknum}")
        for e in self.episodes:
            # Don't set anything if we're already partially through processing
            if e.aud_enc:
                continue
            e.aud_track = tracknum
    
    def set_all_sub_tracks(self, tracknum):
        print(f"Setting all sub tracks to {tracknum}")
        for e in self.episodes:
            if e.sub_enc:
                continue
            e.sub_track = tracknum
        
    def add_source(self, name=None):
        for s in self.sources:
            if s.name == name:
                print("source is already in list, skipping")
                return
        newsrc = Source(name)
        print(f"Added source {newsrc.name}")
        self.sources.append(newsrc)
    
    def get_source(self, name: str) -> Source:
        for s in self.sources:
            if s.name == name:
                return s
        assert False, "Could not find source of this name"
      
    # The money, we'll bisect our crf taking into account the percentage from various sources  
    def calc_target_crf(self):
        runtime_list = [0] * len(self.sources)
        
        # accumulate our runtimes
        for e in self.episodes:
            src_idx = self.sources.index(e.source)
            runtime_list[src_idx] += e.duration_src
            
        def weighted_crf(crf):
            # print(f"Checking crf {crf}")
            total_data_used = 0 # in bytes
            for i in range(0, len(runtime_list)):
                bitrate = self.sources[i].model.bitrate_given_crf(crf)
                total_data_used += (bitrate/8) * (runtime_list[i]/1000)
            return (total_data_used + self.total_audio_size) - self.TARGET_SIZE
        
        botrange, toprange = 1,40
        result = root_scalar(weighted_crf, method="bisect", bracket=[botrange, toprange])
        
        if result.converged:
            print(f"found a valid crf value of {result.root:.6f}")
            # Debug output
            print(f"the values of runtime_list are {runtime_list}")
            print("Estimated bitrate per source:")
            for i in range(0, len(self.sources)):
            # for s in self.sources:
                bitrate = self.sources[i].model.bitrate_given_crf(result.root)
                data_usage = (bitrate/8) * (runtime_list[i]/1000)
                data_usage_perc = (data_usage / self.TARGET_SIZE) * 100
                print(f"{self.sources[i].name}: {bitrate/1000}kbps")
                print(f"{data_usage/1000:.3f}kB, or {data_usage_perc:.3f}% of the total disc capacity")
                print("(should be less than 100 due to audio/sub stream sizes)")
        else:
            print("problem, could not converge")
            exit(1)

        return self._snap_crf(result.root)

    def _snap_crf(self, crf):
        """Snap a CRF/CQ to whatever precision the configured encoder can
        actually act on.

        hevc_nvenc's CQ is 8.8 fixed-point but the driver only honours the top
        2 bits of the fractional byte (see constants.NVENC_CQ_STEP), so any
        finer value silently rounds. We ceil to the next quantum (higher CQ
        -> lower bitrate -> smaller file) so rounding bias pushes us toward
        the undersized side of the size target. Keeps every downstream
        consumer — the encoder, last_attempted_crf, and fine_tune_model data
        points — in agreement about what CRF actually ran.
        """
        if self.profile.video_codec == "hevc_nvenc":
            q = constants.NVENC_CQ_STEP
            return math.ceil(crf / q) * q
        return crf
        
    def add_episode(self, ep_num, vid_src, name=None, origin_src=None, aud_src=None, sub_src=None, sub_track=0, aud_track=0):
        # TODO: make sure we don't add episodes if they already,
        # right now just do a simple number check
        for e in self.episodes:
            if e.ep_num == ep_num:
                print("An episode of this number has already been added, skipping")
                return
            
        # If we don't specify a source for the episode, default to the first
        source_to_use = origin_src
        if not source_to_use:
            # If we don't have a source, create it
            if len(self.sources) == 0:
                self.add_source("Default")
            source_to_use = self.sources[0]
        
        # TODO: this is basically a straight arg passthrough, probably a better way of doing this
        episode = Episode(ep_num, source_to_use, vid_src, name, aud_src, sub_src, sub_track, aud_track)
        
        # If we don't have to encode the audio we can save the passed src as the final data to be muxxed
        if not self.encode_aud:
            episode.aud_enc = episode.aud_src
            
        # Same with subtitles
        if not self.hardsub:
            episode.sub_enc = episode.sub_src
            
        self.episodes.append(episode)
        print(f"Added episode {ep_num} - {name}: {episode.vid_src}")
        print("From source: " + source_to_use.name)
        
    def _record_size_history(self, percent_off):
        """Append a size-error data point and mirror it to the UI's History bar.
        Keeps the persisted list and the live display in sync from one call site.
        """
        self.size_history.append(percent_off)
        if self.ui is not None:
            self.ui.append_history(percent_off)

    def reset_episodes(self):
        for e in self.episodes:
            e.reset()
        
    def scan_episodes(self):
        #self.total_duration = 0
        # Loop through the eps and gather MediaInfo
        for e in self.episodes:
            if e.scanned and e.media_info:
                print("Media Info already scanned")
                continue
            print("Unscanned file detected")
            print(f"Parsing vid source {e.vid_src}")
            e.media_info = MediaInfo.parse(e.vid_src)
            # print(e.media_info.to_json())
            # exit()
            if (e.aud_src
                and not e.audio_info
                and (e.aud_src != e.vid_src)):
                    print(f"Parsing separate audio source {e.aud_src}")
                    e.audio_info = MediaInfo.parse(e.vid_src)
            else:
                print("Audio source is the same as video")
                e.aud_src = e.vid_src
                e.audio_info = e.media_info
            #if e.sub_src and not e.sub_info:
            if (e.sub_src 
                and not e.sub_info
                and (e.sub_src != e.vid_src)):
                    print(f"Parsing separate sub source {e.sub_src}")
                    e.sub_info = MediaInfo.parse(e.sub_src)
            else:
                print("Sub source is the same as video")
                e.sub_src = e.vid_src
                e.sub_info = e.media_info
                
            if e.media_info:
                e.duration_src = float(e.media_info.video_tracks[0].duration)
                #self.total_duration += e.duration_src
                e.scanned = True
                print(f"Scanned file of duration: {e.duration_src}ms")
                #print(e.media_info.to_data())
                
            # Mark up extra flags, like interlacing and framerate
            video_info = e.media_info.video_tracks[0]
            if video_info.hdr_format is not None:
                print("Detected an HDR file")
                e.hdr = True
            if video_info.scan_type and (video_info.scan_type == "Interlaced"):
                print("This video source is interlaced, adding tag")
                e.interlaced = True
            if video_info.framerate_num and video_info.framerate_den:
                print("Detected frame rate attribute, setting")
                e.framerate = video_info.framerate_num + "/" + video_info.framerate_den
                
                
        print("Scanned all files")
        
        # Go through and accumulate the duration
        self.total_duration = 0
        for e in self.episodes:
            self.total_duration += e.duration_src
            
        print(f"Calculated total duration of {self.total_duration/1000} seconds")
        print(f"or {self.total_duration/1000 / 60 / 60:.3f} hours")
        
        # Print some basic information about the project we're about to begin
        proj_kbps = (self.TARGET_SIZE * 8) / (self.total_duration/1000) / 1000
        
        print(f"Calculated a required file bitrate of {proj_kbps:.3f}Kb/s, that's audio and video")
        if proj_kbps <= 1000:
            print("Such a low bitrate per second required this essentially impossible, split to more disks")
        elif proj_kbps <= 5000:
            print("Low bitrate required to hit size requirements, if active 4k video, this will likely be insufficient.")
        elif proj_kbps >= 20000:
            print("We have so much overhead for bitrate here, it is likely more efficient to do a 2-pass encode instead.")
        input("press enter to confirm...")
        
    def extract_subs_and_fonts(self):
        for e in self.episodes:
            if not e.sub_info:
                print(f"Episode {e.ep_num} does not have a sub track, skipping")
                continue
            elif e.subs_extracted:
                print(f"Episode {e.ep_num}'s subs and fonts have already been extracted")
                continue
            # Extract the attachments (fonts)
            if (e.sub_src.suffix == ".mkv") and (self.hardsub) and (e.sub_info.tracks[0].attachments):
                subnames = []
                delim = " / "
                if delim not in e.sub_info.tracks[0].attachments:
                    subnames = [e.sub_info.tracks[0].attachments]
                else:
                    subnames = e.sub_info.tracks[0].attachments.split(delim)
                if not subnames:
                    print(f"{e.ep_num} does not have subtitle attachments")
                else:
                    mkv_extract(e.sub_src, "attachments", self.fonts_dir, list(range(1,len(subnames)+1)), subnames,
                                ui_manager=self.ui)
            # TODO: Intelligent extraction/conversion if subtitles aren't the correct type (srt)
            if (e.sub_src.suffix == ".mkv") and self.hardsub:    
                # Calculate the total number of media tracks before subtitles bc mkvextract indexes them all together
                # num_tracks = len(e.sub_info.video_tracks) + len(e.sub_info.audio_tracks)
                #print(f"{num_tracks} non sub tracks")
                # sub_track_to_extract = num_tracks + e.sub_track
                sub_track_to_extract = e.get_sub_tracknum_absolute()
                format_str = e.sub_info.text_tracks[e.sub_track].format.lower()
                filename = "sub" + str(e.ep_num) + "." + format_str
                mkv_extract(e.sub_src,
                            "tracks",
                            self.workdir,
                            [sub_track_to_extract],
                            [filename],
                            ui_manager=self.ui)
                
                # now that the subs/fonts have been extracted, we can mark them as the final source to be muxxed
                e.sub_enc = (self.workdir / filename)
                e.sub_track = 0 # We've just written a file with only 1 "track", our subtitles
            else:
                # print("subtitles aren't in an mkv file, setting the path directly")
                e.sub_enc = e.sub_src
                print("No subs or fonts to extract")
                # exit(1)
        self.save()
            
        
    def encode_vid(self, ep: Episode, crf, force=False):
        if ep.vid_enc and not force:
            print(f"Encoded video file found at {ep.vid_enc}, skipping...")
            return
        print(f"Encoding video {ep.ep_num} - {ep.ep_name}")
        self.ui.update_episode(ep, len(self.episodes))
        self.ui.update_status(f"Encoding video with CRF {crf:.2f}")
        result = encode_video(ep,
                         out_path=self.workdir,
                         crf=crf,
                         profile=self.profile,
                         hardsub=(self.hardsub or ep.hardsub),
                         fontsdir=self.fonts_dir.absolute(),
                         cropstring=self.cropstring,
                         scalestring=self.scalestring,
                         videotune=self.videotune,
                         keephdr=self.hdr,
                         ui_manager=self.ui)
        if not result:
            print("fatal error encoding video")
            exit(1)
        ep.vid_enc = result

        print(f"Saved encoded video to {ep.vid_enc}")
        self.ui.update_episode_progress(100.0)
        self.save()
        
    def finalize_episode(self, ep: Episode):
            ret = mux_mkv(ep, self.outputdir, ui_manager=self.ui, hardsub=self.hardsub)
            if ret:
                print(f"Marked episode {ep.ep_name} as finalized")
                ep.final = ret
                self.save()

    
    # Run this to build a baseline crf dataset and write it to a file as well
    # as the episode's source object    
    def profile_crf_curve(self, range_lo=20, range_hi=30, ep_num=1) -> None:
        # The power curve I'm using to do coarse crf estimations doesn't converge with less than 4 points
        stepsize = 4
        # High crf to low crf to save time in case we're monitoring live
        crfs = numpy.linspace(range_hi, range_lo, stepsize)
        
        # fix up our crfs with our rounding function
        crfs[:] = [self._snap_crf(c) for c in crfs]
        
        workpath = Path("./profile")
        if not workpath.exists():
            print("creating temporary profiling directory")
            Path.mkdir(workpath)
        
        # We need a new profile curve for each unique video source
        profile_eps = []
        for s in self.sources:
            for e in self.episodes:
                if e.source == s:
                    print(f"Episode {e.ep_num} is of source {s.name}, using")
                    profile_eps.append(e)
                    break
        
        print(f"Need to profile {len(profile_eps)} episodes from {len(self.sources)} sources.")
        
        for ep in profile_eps:
            for crf in crfs:
            # while self.current_crf <= range_hi:
                if crf in ep.source.model.crf_data:
                    print(f"We've previously profiled point {crf}, skipping")
                    continue
                print(f"Profiling video with crf: {crf}")
                self.ui.update_status(f"Profiling video with crf: {crf}")
                # pass stepsize here to record how many crf steps we are about to profile
                self.ui.update_episode(ep, stepsize)
                result = encode_video(ep,
                            out_path=workpath,
                            crf=crf,
                            profile=self.profile,
                            hardsub=(self.hardsub or ep.hardsub),
                            fontsdir=self.fonts_dir.absolute(),
                            #start_time=300, # start after openings
                            stop_time="01:00:00",
                            scalestring=self.scalestring,
                            cropstring=self.cropstring,
                            keephdr=self.hdr,
                            ui_manager=self.ui)
                            #stop_time="00:05:00") # Low value for testing
                if not result.is_file():
                    print("fatal error encoding video")
                    exit(1)
        
                info = MediaInfo.parse(result)
                
                # Uncomment for some extra debug info if need be
                # print(info.video_tracks[0].to_data())
        
                bitrate = info.video_tracks[0].bit_rate
                
                if bitrate is not None:
                    # Add the data to our source object
                    ep.source.model.add_data_point(crf, bitrate)
                    self.save()
                    print(f"crf: {crf}\nbitrate: {bitrate}")
                    # Delete our file to prepare for next loop iteration
                    os.remove(result.absolute())
                else:
                    print("Error reading bitrate from file, critical failure")
                    exit(1)
            
    def process_audio(self):
        # First loop either encodes the audio or validates the codec
        for e in self.episodes:
            # print(e.media_info.audio_tracks[e.aud_track].to_data())
            # exit()
            if e.aud_enc:
                print("Encoded audio file found, skipping encode...")
                continue
            # Check our audio format and take the appropriate action
            if e.audio_info is not None:
                audinfo = e.audio_info
            else:
                assert False, "We should really never hit here"
                print(e.audio_info)
                audinfo = MediaInfo.parse(e.aud_src)
            audformat = audinfo.audio_tracks[e.aud_track].format
            audformat_other = audinfo.audio_tracks[e.aud_track].other_format[0]
            if audformat in self.profile.supported_audio_codecs:
                e.audio_info = audinfo
                # e.aud_enc = e.aud_src
                if not self.encode_aud: # if we aren't forcing an encode
                    if audformat == "DTS" and \
                       "DTS" in self.profile.supported_audio_codecs and \
                       audformat_other != "DTS":
                        print(f"Fancy DTS \"{audformat_other}\" detected, extracting elementary DTS")
                        self.ui.update_status(f"Extracting DTS for episode {e.ep_num}")
                        result = extract_elementary_dts_audio(e,
                            out_path=self.workdir,
                            profile=self.profile,
                            ui_manager=self.ui)
                        if not result:
                            print("Fatal error encoding audio")
                            exit(1)
                        e.aud_enc = result
                        # Set the track to 0 for the new file
                        e.aud_track = 0
                        print(f"Saved DTS elementary stream to {e.aud_enc}")
       
                    print(f"Audio track of type {audinfo.audio_tracks[e.aud_track].format} is valid, continuing")
                    continue
            else:
                print(f"{audformat} isn't in the list of supported codecs, {self.profile.supported_audio_codecs}") 
                # In the case we fall through to here, encode the episode
                print(f"Encoding episode {e.ep_num} audio")
                self.ui.update_status(f"Encoding audio for episode {e.ep_num}")
                result = encode_audio(e,
                            out_path=self.workdir,
                            profile=self.profile,
                            ui_manager=self.ui)
                # save audio file to episode class
                if not result:
                    print("Fatal error encoding audio")
                    exit(1)  
                    
                e.aud_enc = result
                # Set the track to 0 for the new file
                e.aud_track = 0
                print(f"Saved encoded audio to {e.aud_enc}")
            self.save()
                
        
        # Loop over again to tally the audio size
        print("Re-calculating total audio size")
        self.total_audio_size = 0
        for e in self.episodes:
            # get the audio bitrate and add it to cumulative
            # re-scan if we've modified the audio somehow
            if e.aud_enc is not None:
                print(f"Re-scanning episode {e.ep_num} audio")
                e.audio_info = MediaInfo.parse(e.aud_enc)
            else:
                e.aud_enc = e.aud_src
            # print(e.aud_enc)
            # print(audio_info.audio_tracks[0].to_data())
            # exit()
            self.total_audio_size += e.audio_info.audio_tracks[e.aud_track].stream_size
        
        print(f"Processed all audio with a total stream size of {self.total_audio_size} bytes")
        print(f"or {(self.total_audio_size / self.TARGET_SIZE)*100:.3f}% of the disc")
    
    def check_size_threshhold(self):
        # Calculate the total size
        self.total_project_size = 0
        for e in self.episodes:
            if not e.final:
                print(f"ERROR, episode {e.ep_num} hasn't been finalized")
            self.total_project_size += MediaInfo.parse(e.final).tracks[0].file_size
        
        print(f"Total project size is {self.total_project_size} bytes")
        percent_off = (self.total_project_size - self.TARGET_SIZE) / self.TARGET_SIZE
        
        print(f"We are off by {percent_off*100}% and our goal is {constants.THRESHHOLD*100*-1}")
        return percent_off   
     
    # Intended to be run again and again in the state machine until the project threshhold is reached    
    def approach_threshhold(self, crf_hint=None) -> bool:
        # TODO: probably change all this logic to a state machine so nothing falls through the gaps
        # Logic to calculate the new crf mid-project
        if not self.last_percent_off:
            print("Haven't completed the first run")
        elif self.last_percent_off <= 0 and self.last_percent_off > (constants.THRESHHOLD * -1):
            print("We've hit our size threshhold")
            return True
        elif crf_hint and not self.last_attempted_crf :
            print(f"We got a hint on where to start, beginning with crf {crf_hint}")
            self.current_crf = crf_hint
        elif self.fine_tune_model.r_squared and self.last_percent_off <= .20: # if we are over 20% error don't bother
            # If we've fitted our fine tuning function
            # PS, This is written knowing it's taking into account the total file bitrate and not just
            # the video stream, this is okay as we're using a simple linear function to fine-tune
            # that is capable of accounting for it
            print("Using our fine-tuning function to approach the final threshhold")
            target_bitrate = (self.TARGET_SIZE * 8) / self.total_duration # we want this in bits/s
            # Subtract our aiming threshhold because we want to come in undersized
            target_bitrate_w_threshhold = target_bitrate * (1 - constants.THRESHHOLD_TARGET)
            self.current_crf = self.fine_tune_model.crf_given_bitrate(target_bitrate_w_threshhold)
            print(f"We're aiming for a bitrate between {target_bitrate_w_threshhold} and {target_bitrate} ({constants.THRESHHOLD * 100}% within target).\nOur fine tuning model estimates a crf of {self.current_crf}")
        elif not self.fine_tune_model.r_squared or self.last_percent_off > .1: # inverse of above
            print("We're going to use the naiive method to creep up on our target this pass")
            increment = .5  # 50% of our error for linear model
            if self.last_percent_off > constants.THRESHHOLD or self.last_percent_off > 0:
                # If we're oversized we need a big jump to get undersized
                # double change to get us undersized
                print("We're oversized")
                # we don't want it taking forever to get to an undersized state, but
                # we also don't want to overshoot, so we limit the floor of the undersizing step
                percent_to_change = abs(self.last_percent_off) * increment
                percent_to_change = max(percent_to_change, .005) # .5% floor for now
                self.current_crf = self.last_attempted_crf * (1+percent_to_change)
                print(f"We were over by {self.last_percent_off*100}%, adjusting by {percent_to_change*100}%")
            elif self.last_percent_off < (constants.THRESHHOLD * -1):
                # If we're undersized
                print("We're undersized (good)")
                percent_to_change = abs(self.last_percent_off) * (increment)
                self.current_crf = self.last_attempted_crf * (1-percent_to_change)
                print(f"We were under by {self.last_percent_off*100}%, adjusting by {percent_to_change*100}%")            
        
        # We are starting new and haven't processed any episodes
        if not self.eps_to_process:
            print("Starting our processing step fresh")
            self.eps_to_process = self.episodes.copy()
            for e in self.eps_to_process:
                e.reset()
            # Figure out what crf to use
            if crf_hint and not self.last_attempted_crf :
                print(f"We got a hint on where to start, beginning with crf {crf_hint}")
                self.current_crf = crf_hint
            elif not self.last_attempted_crf:
                self.current_crf = self.calc_target_crf()
                print(f"First attempt at a pass, using our power cuve to estimate a crf of {self.current_crf}")
        else:
            print(f"Resuming previously stopped processing with crf of {self.current_crf}")
        
            
        # Snap the newly-computed CRF to the encoder's real precision before
        # doing anything else with it — keeps the value we hand to the
        # encoder, store as last_attempted_crf, and feed to fine_tune_model
        # identical to what actually ran.
        self.current_crf = self._snap_crf(self.current_crf)
        if self.profile.video_codec == "hevc_nvenc" and self.last_attempted_crf is not None:
            prev_q = self._snap_crf(self.last_attempted_crf)
            print(f"Checking for CQ stall between {prev_q} and {self.current_crf}")
            if self.current_crf == prev_q:
                if self.last_percent_off is not None and self.last_percent_off <= 0:
                    # Undersized and can't tighten further without re-encoding the same thing.
                    print(f"Stalled at CQ {prev_q} (undersized by {self.last_percent_off*100:.2f}%). Accepting as final.")
                    return True
                # Oversized stall: force one quantum step up (higher CQ -> smaller file).
                self.current_crf = prev_q + constants.NVENC_CQ_STEP
                print(f"Stalled at CQ {prev_q} while oversized; bumping to {self.current_crf}")

        print(f"Encoding the project with a crf of {self.current_crf}, last attempted was {self.last_attempted_crf}")
        self.encode_episodes(self.eps_to_process, self.current_crf)
        self.last_attempted_crf = self.current_crf
        self.last_percent_off = self.check_size_threshhold()
        self._record_size_history(self.last_percent_off)
        # check_size_threshhold sets self.total_project_size, we can use it to calculate the data for our fine-tuner
        project_bitrate = (self.total_project_size * 8) / self.total_duration # we want this in bits/s
        self.fine_tune_model.add_data_point(self.last_attempted_crf, project_bitrate)
        return False
        # We're all set to loop another time

    # This is where we'll spawn a server and distribute work.
    # For now we just do it locally
    def encode_episodes(self, episode_list, crf):
        total_eps = len(self.episodes)
        current_idx = total_eps - len(episode_list) + 1

        # Add a new line here to print the current episode index
        print(f"Processing episode {current_idx} of {total_eps}")

        while episode_list:
            e = episode_list[0] # get a ref to the first element

            # Update overall progress
            self.ui.update_overall_progress(current_idx-1, total_eps)
            self.ui.update_status(f"CRF {crf:.2f} | Processing {e.ep_name}")

            # We haven't encoded
            if not e.vid_enc:
                self.encode_vid(e, crf)
                self.save()
                e.final = None # We've re-encoded so we'll need to re-finalize
            if not e.final:
                self.finalize_episode(e)
                # if everything went well, this is where we can remove the episode from the list
                episode_list.pop(0)
                current_idx += 1
                self.save()
                

    # The project state machine
    # TODO: Put more resume logic into here and out of approach_threshhold
    def process_project(self, crf_hint=None):
        while self.project_state is not self.state.DONE:
            # The project hasn't been started
            if self.project_state is self.state.NEW:
                self.ui.update_status("Scanning media files...")
                # We need to scan the episodes to get our info
                self.scan_episodes()
                self.project_state = self.state.AUDIO
                self.save()
                continue
            elif self.project_state is self.state.AUDIO:
                self.ui.update_status("Processing audio streams...")
                # Encode or verify our audio streams
                self.process_audio()
                self.project_state = self.state.SUBS
                self.save()
                continue
            elif self.project_state is self.state.SUBS:
                self.ui.update_status("Extracting subtitles and fonts...")
                # Process our subtitles
                self.extract_subs_and_fonts()
                self.project_state = self.state.PROFILE
                self.save()
                continue
            elif self.project_state is self.state.PROFILE:
                # profile our video if we haven't yet
                if not crf_hint:
                    self.ui.update_status("Profiling CRF curve...")
                    self.profile_crf_curve()
                else:
                    print("We have a crf hint, no need to profile")
                self.project_state = self.state.PROCESSING
                self.save()
                continue
            elif self.project_state is self.state.PROCESSING:
                self.ui.update_status("Beginning video encoding...")
                while (not self.approach_threshhold(crf_hint)):
                    self.num_iterations += 1
                    self.save()
                self.project_state = self.state.DONE
                self.save()
                continue
            else:
                print("invalid state")
                exit(1)

        print(f"Yay we're done after {self.num_iterations} tries")
        self.ui.update_status("Complete!")
        self.ui.update_episode_progress(100.0)
        self.ui.update_overall_progress(len(self.episodes), len(self.episodes))