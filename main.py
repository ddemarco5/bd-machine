from project import Project
import constants

proj = Project.load_or_build("firefly")

proj.set_work_dir("workspace")
proj.set_output_dir("encoded")
proj.set_fonts_dir("fonts")
proj.profile = constants.UBP_X700

# proj.encode_aud = True
proj.hdr = True
# proj.hardsub = True

# proj.cropstring = "3840:1920:0:120"
# proj.scalestring = "1920:-1"

proj.add_source("show")
proj.add_source("movie")

proj.add_episode(1,
    vid_src=("Z:/Shows/Firefly (2002)/S01E01 Serenity.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E01 Serenity.srt"),
    origin_src=proj.get_source("show"),
    name="Serenity",
)
proj.add_episode(2,
    vid_src=("Z:/Shows/Firefly (2002)/S01E02 The Train Job.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E02 The Train Job.srt"),
    origin_src=proj.get_source("show"),
    name="The Train Job",
)
proj.add_episode(3,
    vid_src=("Z:/Shows/Firefly (2002)/S01E03 Bushwhacked.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E03 Bushwhacked.srt"),
    origin_src=proj.get_source("show"),
    name="Bushwhacked",
)
proj.add_episode(4,
    vid_src=("Z:/Shows/Firefly (2002)/S01E04 Shindig.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E04 Shindig.srt"),
    origin_src=proj.get_source("show"),
    name="Shindig",
)
proj.add_episode(5,
    vid_src=("Z:/Shows/Firefly (2002)/S01E05 Safe.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E05 Safe.srt"),
    origin_src=proj.get_source("show"),
    name="Safe",
)
proj.add_episode(6,
    vid_src=("Z:/Shows/Firefly (2002)/S01E06 Our Mrs. Reynolds.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E06 Our Mrs. Reynolds.srt"),
    origin_src=proj.get_source("show"),
    name="Our Mrs. Reynolds",
)
proj.add_episode(7,
    vid_src=("Z:/Shows/Firefly (2002)/S01E07 Jaynestown.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E07 Jaynestown.srt"),
    origin_src=proj.get_source("show"),
    name="Jaynestown",
)
proj.add_episode(8,
    vid_src=("Z:/Shows/Firefly (2002)/S01E08 Out of Gas.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E08 Out of Gas.srt"),
    origin_src=proj.get_source("show"),
    name="Out of Gas",
)
proj.add_episode(9,
    vid_src=("Z:/Shows/Firefly (2002)/S01E09 Ariel.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E09 Ariel.srt"),
    origin_src=proj.get_source("show"),
    name="Ariel",
)
proj.add_episode(10,
    vid_src=("Z:/Shows/Firefly (2002)/S01E10 War Stories.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E10 War Stories.srt"),
    origin_src=proj.get_source("show"),
    name="War Stories",
)
proj.add_episode(11,
    vid_src=("Z:/Shows/Firefly (2002)/S01E11 Trash.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E11 Trash.srt"),
    origin_src=proj.get_source("show"),
    name="Trash",
)
proj.add_episode(12,
    vid_src=("Z:/Shows/Firefly (2002)/S01E12 The Message.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E12 The Message.srt"),
    origin_src=proj.get_source("show"),
    name="The Message",
)
proj.add_episode(13,
    vid_src=("Z:/Shows/Firefly (2002)/S01E13 Heart of Gold.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E13 Heart of Gold.srt"),
    origin_src=proj.get_source("show"),
    name="Heart of Gold",
)
proj.add_episode(14,
    vid_src=("Z:/Shows/Firefly (2002)/S01E14 Objects in Space.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/S01E14 Objects in Space.srt"),
    origin_src=proj.get_source("show"),
    name="Objects in Space",
)
proj.add_episode(15,
    vid_src=("Z:/Movies/Serenity.2005.Eng.Fre.Ger.Ita.Spa.Jpn.2160p.BluRay.Remux.HDR.HEVC.DTS.X-SGF.mkv"),
    sub_src=("C:/Users/Dominic/Desktop/firefly/serenity.srt"),
    origin_src=proj.get_source("movie"),
    name="Serenity",
)


proj.process_project()