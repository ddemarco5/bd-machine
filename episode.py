from pathlib import Path

from source import Source

class Episode:
    
    def __init__(self, ep_num, origin_src:Source, vid_src, name=None, aud_src=None, hardsub_src = None, hardsub_track = None, sub_src=-1, sub_track=0, aud_track=0):
        
        # General bookkeeping info
        self.ep_num = ep_num
        self.ep_name = name
        self.media_info = None
        self.hdr = False
        
        # Is this source interlaced? If so, we need to record that as well as its fps
        self.interlaced = False
        # This will be a string in the form of numerator/denominator to pass to ffmpeg
        self.framerate = None
        
        # This can be set per-episode or in a project-wide variable.
        # The actual hardsub_src value is assigned further down alongside the
        # other path-typed source attributes (aud_src/sub_src), so we only
        # initialize the companion media-info field here.
        self.hardsub_track = hardsub_track
        self.hardsub_info = None
        
        # Origin source of the video, as in where it was pulled from
        self.source = origin_src
        
        # video track usage identifier
        self.vid_track = 0
        self.video_info = None
        # audio track usage identifier
        self.aud_track = aud_track
        self.audio_info = None
        # subs track usage identifier
        self.sub_track = sub_track
        self.sub_info = None
        self.subs_extracted = False
        
        # Source information
        self.scanned = False
        self.vid_src = Path(vid_src)
        self.aud_src = None
        self.hardsub_src = None
        self.sub_src = None
        # sub_src=-1 is a sentinel meaning "default to vid_src". Resolve it
        # first so the truthy check below doesn't try Path(-1).
        if sub_src == -1:
            sub_src = self.vid_src
        if aud_src:
            self.aud_src = Path(aud_src)
        if sub_src:
            self.sub_src = Path(sub_src)
        if hardsub_src:
            self.hardsub_src = Path(hardsub_src)
            
        self.duration_src = None

        
        # Encoded (Sink) information
        self.vid_enc = None
        self.aud_enc = None
        self.sub_enc = None
        # Only populated when this episode is locally hardsubbed
        # (i.e. hardsub_src is set but the project is not in hardsub_all mode).
        self.hardsub_enc = None
        self.streamsize_enc = None
        
        # Have we finished processing
        self.final = None
        
    # resets audio and video processing status    
    def reset(self, video=True, audio=False):
        if video:
            self.vid_enc = None
        if audio:
            self.aud_enc = None
        self.final = None
        
    def get_vid_tracknum_absolute(self):
        # Video tracks essentially always come first
        return self.vid_track
        
    def get_aud_tracknum_absolute(self):
        # Add the number of video tracks to the audio track to get the absolute track index
        return len(self.audio_info.video_tracks) + self.aud_track
       
    def get_sub_tracknum_absolute(self):
        # Add the number of video tracks to the audio track to get the absolute track index
        return len(self.sub_info.video_tracks) + len(self.sub_info.audio_tracks) + self.sub_track