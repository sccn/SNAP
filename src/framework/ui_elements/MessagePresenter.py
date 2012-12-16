# -*- coding:utf-8 -*-
import time
from framework.eventmarkers.eventmarkers import send_marker, init_markers


class MessagePresenter(object):
    """
    Base class for all message presenters (auditory, visual, ...). These handle
    only the rendering of simple message-like stimulus events (and are not 
    responsible for their generation).
    """
    def __init__(self,**kwargs):
        """ 
        Construct a new message presenter; if any keyword arguments named "lockduration" or "clearafter" are
        being passed, these override the default behavior of the submit() and submit_wait() functions.
        """
        self.lockduration = kwargs['lockduration'] if kwargs.has_key('lockduration') else 0.0 
        self.clearafter = kwargs['clearafter'] if kwargs.has_key('clearafter') else 0.0
        self._locked_until = 0        
        self._next_clear = 0

    # --- functions to be overridden by subclasses --- 
    
    def _present(self,message):
        """Subclasses override this function to present the message."""    
        pass
    
    def _unpresent(self):
        """Subclasses override this function to remove any currently presented message."""
        pass


    # --- user interface functions ---
    
    def submit_wait(self,message,waiter,lockduration=None,clearafter=None,retryinterval=0.1):
        """
        Submit a message to a presenter, optionally blocking until the presenter is available.
        * message: the message to be presented (usually a string tag)
        * waiter: an object that has a sleep() function, used to implement the blocking
        * lockduration: The presenter may be locked upon successful submission for a specified amount of time,
        * clearafter: The presenter may optionally be cleared after some specific amount of time. 
        * retryinterval: interval, in seconds, at which to re-try submission        
        """
        while not self.submit(message,lockduration,clearafter):
            waiter.sleep(retryinterval)

    def submit(self,message,lockduration=None,clearafter=None):
        """
        Try to submit a new message to the presenter.
        * message: the message string to present 
        * lockduration: Optionally, the presenter may be locked for this amount of time, 
                        which prevents subsequent calls to submit() from succeeding (they instead return false).
        * clearafter: Optionally, the presented message may automatically be cleared after this amount of time
                      has passed (equivalent to calling clear() after that time.
        """
        now = time.time()
        if now > self._locked_until:
            if lockduration is None:
                lockduration = self.lockduration
            if clearafter is None:
                clearafter = self.clearafter
            self._locked_until = time.time()+lockduration
            self._present(message)
            self.clear_after(clearafter)
            return True
        else:
            return False

    def precache(self,message):
        """Pre-cache a message (e.g. sound file or picture) for future instantaneous presentation, if applicable."""
        pass
    
    def clear(self):
        """Clear the previous contents of the presenter, if applicable."""
        self._locked_until = 0
        self._unpresent()
    
    def destroy(self):
        """Disable/remove the presenter, if applicable."""
        pass
    
    def unlock(self):
        """Forcibly unlock the presenter."""
        self._locked_until = 0

    def clear_after(self,clearafter):
        """Clear the presenter after some time."""
        if clearafter > 0:
            self._next_clear = time.time() + clearafter
            taskMgr.doMethodLater(clearafter, self._clear_task, 'MessagePresenter.clear()')

    def _clear_task(self,task):
        """Task to clear the icon after done."""
        if time.time() >= self._next_clear-0.1: # we don't clear if the clear schedule has been overridden in the meantime...                                
            self.clear()                        # the 0.1 is a timing tolerance parameter
        return task.done 
            
    def marker(self,markercode):
        """Send a marker."""
        send_marker(markercode)
