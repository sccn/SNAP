from MessagePresenter import MessagePresenter
import random

class BroadcastPresenter(MessagePresenter):
    """
    A proxy for a group of message presenters -- the messages are forwarded to all presenters.
    """
        
    def __init__(self,
                 presenters=[],        # the backend presenter to wrap  
                 *args,**kwargs 
                 ):        
        MessagePresenter.__init__(self,*args,**kwargs)
        self.presenters = presenters

    def submit(self,message,lockduration=None,clearafter=None):
        """Submit a new message."""
        self.marker(220)
        for p in self.presenters:
            p.submit(message,lockduration,clearafter)
        return True
        

    def clear(self):
        """Clear the content."""
        for p in self.presenters:
            p.clear()
    
    def precache(self,message):
        """Pre-cache a message."""
        for p in self.presenters:
            p.precache(message)

    def unlock(self):
        """Manually unlock the presenter (always succeeds)."""
        for p in self.presenters:
            p.unlock()
