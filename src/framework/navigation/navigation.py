import pyrecast
from pandac.PandaModules import VBase4,Point3,Vec3
import time

# ===========================================================================================
# === This module contains classes for path-finding and navigation (using recast/detour). ===
# ===========================================================================================


def panda2detour(pos):
    """Convert a point from the Panda3d to detour coordinate system."""
    return pyrecast.dtPoint3(pos[0],pos[2],-pos[1])

def detour2panda(pos,y=None,z=None):
    """Convert a point from the detour to the Panda3d coordinate system."""
    if y is None and z is None:
        get = pyrecast.floatp_getitem
        return Point3(get(pos,0),-get(pos,2),get(pos,1))
    else:
        return Point3(pos,-z,y)



class NavMesh:
    """
    A recast navigation mesh (and some query data structures).
    Note: pyrecast offers far more functionality than what is exposed here; the extra features are relatively
          straightforward to add if needed (but getting the type conversions right takes some work).
    """

    def __init__(self, navmesh, maxnodes=65536):
        """Initialize with a given navmesh."""    
        self.mesh = pyrecast.dtLoadMesh(navmesh)
        self.filter = pyrecast.dtQueryFilter()
        self.query = pyrecast.dtNavMeshQuery()
        status = self.query.init(self.mesh,maxnodes) #.disown()
        
    def nearest_point(self,
                      pos=(0,0,0),  # query position, in panda3d coordinates
                      radius=5):    # query radius
        """
        Find the nearest point on a navigable polygon in the navmesh. 
        Returns a tuple of (polyref,point).
        """
        radius = pyrecast.dtPoint3(radius,radius,radius)
        tmp_polyref = pyrecast.new_uintp(1)
        tmp_point = pyrecast.dtPoint3(0,0,0)
        self.query.findNearestPoly(panda2detour(pos),radius,self.filter,tmp_polyref,tmp_point) #.disown()
        return [tmp_polyref,tmp_point]
        
    def nearest_edge_point(self,
                           loc,          # in detour coordinates; as returned by, for example, nearest_point (format: [polyref,point])
                           radius=5      # query radius
                           ):
        """
        Find the nearest edge point for a given location (location as returned by nearest_point()) 
        Returns a tuple of (polyref,point), i.e. same format as nearest_point()
        """
        tmp_point = pyrecast.dtPoint3(0,0,0)
        self.query.closestPointOnPolyBoundary(pyrecast.uintp_getitem(loc[0],0), loc[1], tmp_point) #.disown()
        return [loc[0],tmp_point]

    def is_reachable(self,
                     a,                 # in panda3d coordinates
                     b,                 # in panda3d coordinates
                     tolerance=0.5,
                     max_path=1000
                     ):
        """ Check if two points are reachable from each other. """
        a = self.nearest_point(a,radius=tolerance)
        b = self.nearest_point(b,radius=tolerance)
        tmp_path = pyrecast.new_uintp(max_path)
        tmp_pathcount = pyrecast.new_intp(1)
        status = self.query.findPath(pyrecast.uintp_getitem(a[0],0),pyrecast.uintp_getitem(b[0],0),a[1],b[1],self.filter, tmp_path, tmp_pathcount, int(max_path))
        #result = not ((pyrecast.uintp_getitem(status,0) & (1<<30)) == 0)
        result = pyrecast.dtStatusSucceed(status)
        #status.disown()
        return result


class NavCrowd:
    """
    A crowd of detour agents.
    """

    def __init__(self,
                 nav,                   # a NavMesh object
                 maxagents=10,          # The maximum number of agents the crowd can manage. [Limit: >= 1]
                 maxagentradius=0.6,    # The maximum radius of any agent that will be added to the crowd. [Limit: > 0]
                 ):
        """Initialize the crowd."""        
        self.nav = nav
        self.crowd = pyrecast.dtCrowd()
        self.crowd.init(maxagents,maxagentradius,self.nav.mesh)
        self.debuginfo = pyrecast.dtCrowdAgentDebugInfo()
        self.last_time = time.time()
        self._active_indices = []        # the list of indices that are currently in use
        taskMgr.add(self.update, 'NavCrowd.update()')

    def destroy(self):
        taskMgr.remove('NavCrowd.update()')

    def active_indices(self):
        """ Get the list of agent indices that are currently in use. """
        return self._active_indices

    def add_agent(self,
                  loc=(0,0,0),                  # Initial location; can be either a Panda3d or a detour position type (in the respective native coordinate system)
                  radius = 0.6,                 # Agent radius. [Limit: >= 0]
                  height = 2,                   # Agent height. [Limit: > 0]
                  maxaccel = 3,                 # Maximum allowed acceleration. [Limit: >= 0]
                  maxspeed = 3.5,               # Maximum allowed speed. [Limit: >= 0]
                  collisionquery_range = 24,    # Defines how close a collision element must be before it is considered for steering behaviors. [Limits: > 0]
                                                # this value is implicity multiplied by the agent radius
                  pathoptimization_range = 60,  # The path visibility optimization range. [Limit: > 0]
                                                # this value is implicity multiplied by the agent radius
                  obstacleavoidance_type = 3,   # The index of the avoidance configuration to use for the agent. [Limits: 0 <= value <= #DT_CROWD_MAX_OBSTAVOIDANCE_PARAMS] 
                  separation_weight = 1,        # How aggresive the agent manager should be at avoiding collisions with this agent. [Limit: >= 0]
                  # Flags that impact steering behavior. (See: #UpdateFlags)
                  anticipate_turns = True,
                  avoid_obstacles = False,
                  crowd_separation = False,
                  optimize_vis = True,
                  optimize_topo = True,
                  ):
        """
        Add a new agent to the crowd at some initial location. Returns the index of the agent.
        """
        params = pyrecast.dtCrowdAgentParams()
        params.radius = radius
        params.height = height
        params.maxAcceleration = maxaccel
        params.maxSpeed = maxspeed
        params.collisionQueryRange = collisionquery_range*radius
        params.pathOptimizationRange = pathoptimization_range*radius
        params.obstacleAvoidanceType = obstacleavoidance_type
        params.separationWeight = separation_weight
        params.updateFlags = 0
        if anticipate_turns:
            params.updateFlags |= pyrecast.DT_CROWD_ANTICIPATE_TURNS
        if optimize_vis:
            params.updateFlags |= pyrecast.DT_CROWD_OPTIMIZE_VIS
        if optimize_topo:
            params.updateFlags |= pyrecast.DT_CROWD_OPTIMIZE_TOPO
        if avoid_obstacles:
            params.updateFlags |= pyrecast.DT_CROWD_OBSTACLE_AVOIDANCE
        if crowd_separation:
            params.updateFlags |= pyrecast.DT_CROWD_SEPARATION
        if hasattr(loc,'__getitem__'):
            if len(loc) == 2:
                loc = loc[1]
            else:
                loc = panda2detour(loc)
        elif isinstance(loc,Point3):
            loc = panda2detour(loc[1])
        else:
            raise Exception("Unrecognized location data type")
        idx = self.crowd.addAgent(loc,params)
        self._active_indices.append(idx)
        return idx
    
    def remove_agent(self,idx):
        """
        Remove an agent from the crowd.
        """
        self._active_indices.remove(idx)
        self.crowd.removeAgent(idx)

    def request_move_target(self,idx,loc):
        """
        Enqueue a new move target for agent #idx.
        The location must have been resolved via e.g. NavMesh.nearest_point() and is in detour coordinates.
        """
        self.crowd.requestMoveTarget(idx,pyrecast.uintp_getitem(loc[0],0),loc[1])
    
    def replan_move_target(self,idx,loc):
        """
        Re-plan the current move target for agent #idx.
        The location must have been resolved via e.g. NavMesh.nearest_point() and is in detour coordinates.
        """
        self.crowd.requestMoveTargetReplan(idx,pyrecast.uintp_getitem(loc[0],0),loc[1])

    def adjust_move_target(self,idx,loc):
        """
        Adjust the current move target for agent #idx.
        The location must have been resolved via e.g. NavMesh.nearest_point() and is in detour coordinates.
        """
        self.crowd.adjustMoveTarget(idx,pyrecast.uintp_getitem(loc[0],0),loc[1])
    
    def agent_status(self,idx):
        """
        Query the status of an agent. The output positions and velocities are in Panda3d coordinates.
        """
        agent = self.crowd.getAgent(idx)
        # translate a few coordinates
        class status:
            pass
        result = status()
        result.npos = detour2panda(agent.npos)
        tmp = detour2panda(agent.vel)
        result.vel = Vec3(tmp.getX(),tmp.getY(),tmp.getZ())
        return result
            
    def update(self,task):
        """
        Internal update function, called once per frame.
        """
        cur_time = time.time()
        self.crowd.update(cur_time - self.last_time,self.debuginfo)
        self.last_time = cur_time
        return task.cont

