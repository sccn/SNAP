# -*- coding:utf-8 -*-
from MessagePresenter import MessagePresenter
from panda3d.core import *
from direct.gui.DirectGui import *
from direct.gui.OnscreenImage import OnscreenImage

class ImagePresenter(MessagePresenter):
    """
    A display that can present images with a fixed (or optionally randomly chosen) position,
    size and other display properties (e.g. coloring).   
    
    See also MessagePresenter for usage information.
    """
    
    def __init__(self,
                 pos=(-0.25,0.5),       # position of the image center in the aspect2d viewport
                                        # may also be a callable object (e.g.a draw from a random number generator)
                 scale=0.2,             # scaling of the image; may also be callable
                 rotation=(0,0,0),      # yaw, pitch, roll -- the most relevant is the roll coordinate; may also be callable
                 color=(1,1,1,1),       # (r,g,b,a) image color
                 renderviewport=None,   # the parent viewport if desired
                 image='blank.tga',     # the initial image to present
                 *args,**kwargs
                 ):
        
        """Construct a new ImagePresenter."""
        MessagePresenter.__init__(self,*args,**kwargs) 
        self.pos = pos
        self.scale = scale
        self.rotation = rotation
        self.color = color
        self.renderviewport = renderviewport
        
        # set up the text panel...
        #if not (type(self.pos) is List or type(self.pos) is tuple):
            #pos = self.pos()
        #if callable(self.scale):
            #scale = self.scale()
        #if callable(self.rotation):
            #rotation = self.rotation()
        #if callable(self.color):
            #color = self.color()
        self.icon = OnscreenImage(image=image,pos=(pos[0],0,pos[1]),scale=scale,hpr=rotation,color= ((0,0,0,0) if image=="blank.tga" else self.color),parent=self.renderviewport)
        self.icon.setTransparency(TransparencyAttrib.MAlpha)

    def _present(self,message):
        self.icon.setImage(message.strip())
        self.icon.setTransparency(TransparencyAttrib.MAlpha)
        # select remaining properties randomly, if applicable            
        # if callable(self.pos):
        #    p = self.pos()
        #    self.icon.setPos(p[0],p[1],p[2])
        # if callable(self.scale):
        #    self.icon.setScale(self.scale())
        # if callable(self.rotation):
        #    rot = self.rotation()
        #    self.icon.setHpr(rot[0],rot[1],rot[2])
        col = self.color #() if callable(self.color) else self.color 
        self.icon.setColor(col[0],col[1],col[2],col[3])
        self.marker(222)

    def _unpresent(self):
        try:
            self.marker(223)
            self.icon.setColor(0,0,0,0)
        except:
            pass

    def destroy(self):
        self.icon.removeNode()

    def precache(self,message):
        loader.loadTexture(message)
     