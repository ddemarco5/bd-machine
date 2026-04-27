BD_SIZE = 25025314816 # bytes, BD-R single layer
BD_DL_SIZE = 50050629632 # BD-R dual layer

# THRESHHOLD = .02 # 2% size threshhold for now
THRESHHOLD = .04 # 4% seems to be the best granularity we can get with nvenc cq mode
THRESHHOLD_TARGET = THRESHHOLD / 2 # aim smack dab in the threshhold

# Smallest CQ increment hevc_nvenc will actually act on. Although ffmpeg stores
# -cq as 8.8 fixed-point, the NVIDIA driver only honors the top 2 bits of the
# fractional byte, giving an effective resolution of 0.25. Confirmed empirically
# via binary-search test (see test.py) across multiple base CQ values.
NVENC_CQ_STEP = 0.25

# https://www.sony.com/electronics/support/res/manuals/4579/f2b13b14d596d6574a73a689b5d4b0dc/45796631M.pdf
class BDP_S3700:
    # video info
    video_codec = "libx264"
    video_level = "4.1"
    pixel_format = "yuv420p"
    resolution = (1920,1080)
    
    # audio info
    audio_codec = "aac"
    # "Dolby Digital, LPCM, AAC, MP3, Vorbis" from the manual
    supported_audio_codecs=["AC-3","AAC","MP3","VORBIS"] # VORBIS might be wrong, verify
    audio_qual = "10"
    
    # subtitle info
    subs_codec = "text"
    
    
# this is what Greg has   
# https://www.sony.com/electronics/support/res/manuals/4698/004dd925e705a2ef013ac81130d0ab2a/46984061M.pdf
class UBP_X700:
    # video info
    # video_codec = "libx265"
    video_codec = "hevc_nvenc"
    video_level = "5.1"
    pixel_format = "yuv420p10le"
    resolution = (3840,2160)
    
    # audio info
    audio_codec = "aac"
    # "Dolby Digital, LPCM, AAC, MP3, Vorbis" from the manual
    # NOTE: mkv playback does support dts audio contrary to the manual matrix. Potentially added in software update
    supported_audio_codecs=["E-AC-3","AC-3","DTS","AAC","MP3","VORBIS"] # VORBIS might be wrong, verify
    audio_qual = "10"
    
    # subtitle info
    # NOTE ts and m2ts do not support text subtitles, need subtitle editor or tsmuxer which have
    # font renderers to convert them
    subs_codec = "text"
    
    
class TABLET:
    # video info
    video_codec = "libx265"
    video_level = "5.1"
    pixel_format = "yuv420p"
    resolution = (1920,1200)
    
    # audio info
    supported_audio_codecs=["E-AC-3","AC-3","DTS","AAC","MP3","VORBIS"] # VORBIS might be wrong, verify
    audio_qual = "10"
    
    # subtitle info
    # NOTE ts and m2ts do not support text subtitles, need subtitle editor or tsmuxer which have
    # font renderers to convert them
    subs_codec = "text"