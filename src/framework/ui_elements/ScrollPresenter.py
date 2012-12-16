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
                 autoclear=3,       # interval at which to shift up old messages (one line at a time), in seconds or None
                 prompt = '',       # the prompt to prepend to every non-empty message
                 *args,**kwargs):
        if not ("height" in kwargs):
            kwargs["height"] = numlines
        TextPresenter.__init__(self,*args,**kwargs)
        self.numlines = numlines
        self.lines = ['']*self.numlines
        self.prompt = prompt
        if autoclear is not None:
            taskMgr.doMethodLater(autoclear,self._autoclear,'Scroll.autoclear')

    def _present(self,message):
        self.lines = self.lines[1:]
        if not (message == ""):            
            message = self.prompt + message.strip()
        if '' in self.lines:
            # insert at the position of the oldest blank line
            self.lines.insert(max(1,self.lines.index('')),message)
        else:
            # otherwise append at the end
            self.lines.append(message)
        self.marker(224)
        TextPresenter._present(self,"\n".join(self.lines))
        
    def _unpresent(self):        
        self.lines = ['']*self.numlines        
        TextPresenter._unpresent(self)
        self.marker(225)
        
    def _autoclear(self,task):
        self._present("")
        return task.again