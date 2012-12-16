# This file contains the settings for the Panda3d engine that are loaded by default unless configured otherwise.
# See http://www.panda3d.org/manual/index.php/List_of_All_Config_Variables for a complete list.

win-origin 50 50
win-size 2000 800
fullscreen #f
undecorated #f
cursor-hidden #f
show-frame-rate-meter #t


# below are a few settings that are disabled by default but are often relevant for experiments
# textures-power-2 none   			# uncomment this if your graphics card supports pixel-accurate textures (otherwise textures will be upscaled)
# audio-library-name p3openal_audio # uncomment this if your movies play back without audio (note: this library can be slower than the default)

audio-library-name p3fmod_audio
fmod-use-asio #t
