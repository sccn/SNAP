# This file contains the settings for the Panda3d engine that are loaded by default unless configured otherwise.
# See http://www.panda3d.org/manual/index.php/List_of_All_Config_Variables for a complete list.

win-origin 0 0
win-size 2304 1366
#win-origin 2580 200
#win-size 1500 500
fullscreen #f
undecorated #t
cursor-hidden #t
show-frame-rate-meter #t


# below are a few settings that are disabled by default but are often relevant for experiments
# textures-power-2 none   			# uncomment this if your graphics card supports pixel-accurate textures (otherwise textures will be upscaled)

#audio-library-name p3openal_audio # uncomment this if your movies play back without audio (note: this library can be slower than the default)
audio-library-name p3fmod_audio
#fmod-use-asio #t
#fmod-use-surround-sound #f.