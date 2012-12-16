# -*- coding:utf-8 -*-
from MessagePresenter import MessagePresenter
from direct.gui.DirectGui import *
from panda3d.core import TextNode

class TextPresenter(MessagePresenter):
    """
    A panel that can display a piece of multi-line text.  
    It has fixed display properties such as font, color, size, position, etc.
    
    See also MessagePresenter for usage information.
    """
    
    def __init__(self,
                 horzmargin=0.5,        # horizontal margin in characters
                 vertmargin=1,          # vertical margin in charaters
                 width=30,              # width of the text box in characters
                 height=5,              # height of the text box in lines
                 scale=0.05,            # scaling of the text box
                 pos=(-3.1,-0.6),         # position of the upper-left corner inside the aspect2d viewport
                 font='arial.ttf',      # font to use for the text
                 align='left',          # alignment of the text (can be 'left', 'center', or 'right')
                 textcolor=(1,1,1,1),   # (r,g,b,a) text color
                 framecolor=(0,0,0,1),  # (r,g,b,a) frame color
                 *args,**kwargs
                 ): 
        
        """Construct a new TextPresenter."""
        MessagePresenter.__init__(self,*args,**kwargs)

        if align == 'left':
            align = TextNode.ALeft
        elif align == 'right':
            align = TextNode.ARight
        else:
            align = TextNode.ACenter

        text = TextNode('TextPresenter')
        text.setText('\n')
        font = loader.loadFont(font)
        text.setFont(font)
        text.setAlign(align)
        text.setWordwrap(width)
        text.setTextColor(textcolor[0],textcolor[1],textcolor[2],textcolor[3])
        if framecolor[3] > 0:
            text.setCardColor(framecolor[0],framecolor[1],framecolor[2],framecolor[3])
            text.setCardActual(-horzmargin,width+horzmargin,-(height+vertmargin),vertmargin)
        self.text = text
        self.text_nodepath = aspect2d.attachNewNode(text)
        self.text_nodepath.setScale(scale)        
        self.pos = pos        
        self.textcolor = textcolor
        pos = self.pos
        self.text_nodepath.setPos(pos[0],0,pos[1])

    def _present(self,message):
        try:
            pos = self.pos
            self.text_nodepath.setPos(pos[0],0,pos[1])
            self.text.setText(message)
            self.text.setTextColor(self.textcolor[0],self.textcolor[1],self.textcolor[2],self.textcolor[3])
            self.marker(226)
        except:
            print "Issue displaying text"

    def _unpresent(self):
        self.text.setText(' ')
        self.marker(227)  

    def destroy(self):
        self.text_nodepath.removeNode()
