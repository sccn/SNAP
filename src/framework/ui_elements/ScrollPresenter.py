# -*- coding:utf-8 -*-
from TextPresenter import TextPresenter

class ScrollPresenter(TextPresenter):
    """
    A scrolling text panel with a specified number of lines,
    and inherits all functionality of a TextPresenter. New text is inserted at the 
    bottom, and previous text scrolls upwards.
    
    See also MessagePresenter for usage information.
    """
    
    def __init__(self,
                 numlines=5,        # number of lines that may be simultaneously displayed
                 autoclear=5,       # interval at which to shift up old messages (one line at a time), in seconds or None
                 prompt = '',       # the prompt to prepend to every non-empty message
                 padding=3,         # number of padding lines at the end
                 *args,**kwargs):
        if not ("height" in kwargs):
            kwargs["height"] = numlines
        TextPresenter.__init__(self,*args,**kwargs)
        self.numlines = numlines
        self.padding = padding
        self.lines = []
        self.prompt = prompt
        self.autoclear = autoclear

    def _present(self,message):
        self.marker("ScrollPresenter::_present(%s)" % message)
        if len(self.lines)>0 and (self.numlines - len(self.lines) < self.padding):
            # scroll up by one
            self.lines = self.lines[1:]
        # append message at the end
        self.lines.append(self.prompt + message.strip())
        self.marker(224)
        # draw padded with blank lines
        TextPresenter._present(self,"\n".join(self.lines + ['']*(self.numlines - len(self.lines))))
        if self.autoclear is not None:
            taskMgr.doMethodLater(self.autoclear,self._doautoclear,'Scroll.autoclear')

    def _unpresent(self):        
        self.lines = []
        TextPresenter._unpresent(self)
        self.marker(225)
        
    def _doautoclear(self,task):
        # scroll up by one
        if len(self.lines) > 0:
            self.lines = self.lines[1:]
        TextPresenter._present(self,"\n".join(self.lines + ['']*(self.numlines - len(self.lines))))
        return task.done