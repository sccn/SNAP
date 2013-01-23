# ====================================================
#  This module is run on the experimenter's computer.
#  It controls almost all aspects of the experiment,
#  including the highest level of the code.
#
#  Upon startup, the module connects to two remote
#  instances of SNAP running the LSE_GameClient module.
# ====================================================

# Camera bitmasks (can be used to hide objects from certain types of cameras):
# - 0: satmap camera for the first player
# - 1: satmap camera for the second player
# - 2: experimenter's camera
# - 3: viewport camera of the first player
# - 4: viewport camera of the second player


# Panda3d
from direct.task.TaskManagerGlobal import taskMgr
from direct.task import Task
from pandac.PandaModules import Vec3, Vec4, Mat4, Point3, BitMask32, PNMImage, Camera, NodePath, WindowProperties, GeomVertexReader, ConfigVariableSearchPath, TransparencyAttrib, TransformState, VBase4
#noinspection PyUnresolvedReferences
from panda3d.bullet import BulletTriangleMesh, BulletTriangleMeshShape, BulletRigidBodyNode, BulletHeightfieldShape, BulletWorld, BulletDebugNode, BulletBoxShape, BulletVehicle, ZUp

# SNAP framework
from framework.latentmodule import LatentModule
from framework.ui_elements import ScrollPresenter, TextPresenter, EventWatcher
from framework.ui_elements.WorldspaceGizmos import *
from framework.basicstimuli import BasicStimuli
from framework.eventmarkers.eventmarkers import send_marker
import framework.navigation.navigation as navigation
import framework.tickmodule
import pylsl.pylsl as pylsl
import rpyc

# Python
import random, time, threading, math, traceback, itertools


# =======================
# === MAGIC CONSTANTS ===
# =======================

server_version = '0.3'      # displayed to the experimenter so he/she can keep track of versions
max_duration = 500000       # the maximum feasible duration (practically infinity)
max_agents = 20             # maximum number of simultaneous AI-controlled agents
screen_shuffle = [1,2,3]    # the order of the screen indices from left to right (for handedness switch or random permutation)
screen_aspect = 1200/700.0  # screen aspect ratio that this should run on (note: this is the *client* aspect ratio)

# ========================
# === HELPER FUNCTIONS ===
# ======================== 

def livecoding(fn):
    """
    A decorator that displays exceptions but keeps them from leaking out of a given function. Can be used to halt and
    fix (i.e., redeclare) the function at run-time, re-invoke the corrected version, and continue.
    """
    def wrapped(*args,**kwargs):
        try:
            # run the actual function
            return fn(*args,**kwargs)
        except LatentModule.ModuleCancelled:
            # don't hickup if this exception is due to the experimenter cancelling the run
            pass
        except Exception as e:
            # got a regular exception: display it, but eat it
            print "Exception " + str(e) + " in " + fn.__name__
            try:
                send_marker('Experiment Control/Status/Error/%s' % (str(e),))
            except:
                pass
            try:
                traceback.print_exc()
            except:
                print "Traceback failed."
            # allow the user to intervene and fix the code
            # NOTE: If you get here you can fix fn and re-run it -- once it is fixed replace it by evaluating something like: Main.my_old_broken_function = fn
            print "Ignoring / Breakpoint..."
    return wrapped


def clamp(x,lo=0.0,hi=1.0):
    return min(max(x,lo),hi)


def smoothstep(x,edge0=0.0,edge1=1.0):
    """ Sigmoidal interpolation between two values. """
    t = clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def rect(tl,br):
    """ Turns a pair of top/left, bottom/right coordinates into a rect (which is left,right,top,bottom). """
    return tl[0],br[0],tl[1],br[1]

@livecoding
def line_of_sight(physics,              # bullet physics world 
                  src_pos,              # position of the source object (the viewer), as Point3
                  dst_pos,              # position of the destination object, as Point3
                  src_dir=None,         # view direction of the source object, as Vec3
                  dst_dir=None,         # view direction of the destination object, as Vec3
                  src_maxsight=50,      # maximum view distance 
                  src_fov=90,           # total field of view of the source object (in degrees)
                  dst_fov=90,           # total field of view of the destination object (in degrees); this is for advanced classification of the constellation between both objects
                  src_margin=1.5,       # maximum bounds of the source object's geometry
                  dst_margin=1.5        # maximum bounds of the destination object's geometry
                  ):
    """
    Do a line-of-sight check between a source position and destination position (optionally including view direction(s)).
    This function returns one of the following values:
    * None if there is no line of sight, otherwise a string
    * 'front' if both objects are facing each other
    * 'side' if the source object views the destination object from the side
    * 'behind' if the source object views the destination object from behind
    * 'undetermined' if the source object views the destination object, but the angle of incidence is undetermined (e.g. if both objects have the same position, or if the destination orientation is not known)
    """ 
    ray = dst_pos - src_pos
    distance = ray.length()
    if not ray.normalize():
        return "undetermined"
    if (src_dir is not None) and not src_dir.normalize():
        return None
    if dst_dir is not None:
        if not dst_dir.normalize():
            dst_dir = None
    if distance < src_maxsight and distance > 0 and (src_dir is None or abs(src_dir.angleDeg(Vec3(ray))) < src_fov/2):
        # with line-of-sight?
        hittest = physics.rayTestAll(src_pos,dst_pos)
        has_los = True
        for k in range(hittest.getNumHits()):
            hit = hittest.getHit(k)
            # make sure that the hit is not within the bounds of the two objects                                                    
            if (hit.getHitFraction() < 1.0) and (hit.getHitFraction()*distance > src_margin) and (abs(distance - hit.getHitFraction()*distance) > dst_margin):
                has_los = False # found a regular world intersection
                break
        if has_los:
            # src has a line-of-sight to dst; classify what type of sighting it is
            if dst_dir is None:
                return "undetermined"
            else:
                angle = abs(dst_dir.angleDeg(-Vec3(ray)))
                if angle < dst_fov/2:
                    return "front"
                elif angle < 135:
                    return "side"
                else:
                    return "behind"
        else:
            return None

@livecoding
def generate_positions(scenegraph,                  # the scene graph for which the positions shall be generated. Positions will be relative to the root node.
                       navmesh=None,                # optionally a navmesh on the scene graph to enforce reachability constraints
                       physics=None,                # optionally a bullet physics world to enforce line-of-sight constraints

                       # placement parameters
                       objectnames=None,            # the names of objects to whose surfaces the points should be constrained
                       num_positions=1,             # the number of positions to generate

                       # position constraints (lists of points)
                       reachable_from=None,         # optionally a set of positions from which the generated positions shall be reachable
                       invisible_from=None,         # optionally a set of positions from which the generated positions shall be invisible
                       away_from=None,              # optionally a set of positions from which the generated positions should be distanced by at least some radius
                       nearby_to=None,              # optionally a set of positions from which the generated positions should be distanced by at most some radius
                       within_cone=None,            # list of conic constraints (each is a tuple/list of (origin, direction)
                       within_box=None,             # optional box constaint ((minx,maxx),(miny,maxy),(minz,maxz))

                       # extra parameters
                       nearby_radius=500,           # points may be at most this many meters away from any position in nearby_to (can be a scalar or a Point3 for a scaled ellipsoid range, or a list of such values to provide one value for each position in nearby_to)
                       away_radius=75,              # points have to be at least this many meters away from any position in away_from (can be a scalar or a Point3 for a scaled ellipsoid range, or a list of such values to provide one value for each position in away_from)
                       within_cone_angle = 90,      # angle (e.g., fov) of the conic constraints
                       visibility_params=None,      # optional parameters to override in the visibility check
                       reachability_param='all',    # if 'all', the position needs to be reachable from all points in reachable_from, if 'any' it suffices
                                                    # if the position is reachable from a single point in reachable_from
                       nearby_param='all',          # if 'all', the position must be within radius for all points in nearby_to, if 'any' it's enough if a single position is within range
                       within_cone_param='all',     # if 'all', the position must be within the cone for all constraints in within_cone, if 'any' it's enough if a single constraint is satisfied
                       snap_to_navmesh_radius=1,    # if there is a discrepancy between scene graph geometry and navmesh, this is the radius (in meters) within which to snap positions to the navmesh
                       output_coord_sys='panda',    # the coordinate system of the output points; can be 'panda', i.e., Point3(x,y,z), or 'detour', yielding [pyrecast.uintp,pyrecast.floatp]
                       max_retries=3000,            # maximum number of retries per position (returns one less if not satisfiable)
                       snap_to_navmesh=True,        # whether to snap the positions to the navmesh; note that the NM is a bit coarse in some areas...
                       ):
    """
    Generate a list of world-space positions for an existing scene graph that satisfy a number of criteria, such as being reachable from
    a collection of points, being invisible from a collection of points, being on the surface of an object with a particular name, or being
    within a given radius around a particular object.
    """
    if not visibility_params:
        visibility_params = {}

    # find all scene nodes with the desired name
    if not (type(objectnames) is list or type(objectnames) is tuple):
        objectnames = [objectnames]
    nodes = []
    for n in objectnames: 
        nodes += scenegraph.findAllMatches('**/' + n + '/-GeomNode')

    # reformat into lists
    if reachable_from is not None and type(reachable_from) is not list and type(reachable_from) is not tuple:
        reachable_from = [reachable_from]
    if invisible_from is not None and type(invisible_from) is not list and type(invisible_from) is not tuple:
        invisible_from = [invisible_from]
    if away_from is not None and type(away_from) is not list and type(away_from) is not tuple:
        away_from = [away_from]
    if nearby_to is not None and type(nearby_to) is not list and type(nearby_to) is not tuple:
        nearby_to = [nearby_to]
    if away_radius is not None and type(away_radius) is not list and type(away_radius) is not tuple:
        away_radius = [away_radius]*len(away_from) if away_from else [away_radius]
    if nearby_radius is not None and type(nearby_radius) is not list and type(nearby_radius) is not tuple:
        nearby_radius = [nearby_radius]*len(nearby_to) if nearby_to else [nearby_radius]

    # go through the position lists and reformat them into Point3 if necessary
    def reformat(l):
        if l is not None:
            for k in range(len(l)):
                if type(l[k]) is list or type(l[k]) is tuple:
                    l[k] = Point3(l[k][0],l[k][1],l[k][2])
        return l
    reachable_from = reformat(reachable_from)
    invisible_from = reformat(invisible_from)
    away_from = reformat(away_from)
    nearby_to = reformat(nearby_to)

    # reformat the radius values into Point3 if necessary
    for k in range(len(nearby_radius)):
        if type(nearby_radius[k]) is not Point3:
            nearby_radius[k] = Point3(nearby_radius[k],nearby_radius[k],nearby_radius[k])
    for k in range(len(away_radius)):
        if type(away_radius[k]) is not Point3:
            away_radius[k] = Point3(away_radius[k],away_radius[k],away_radius[k])

    results = []
    for k in range(num_positions):
        # propose random locations until all conditions are satisfied...
        retry = 0
        reachability_fails = 0
        visibility_fails = 0
        box_fails = 0
        cone_fails = 0
        away_fails = 0
        nearby_fails = 0
        for retry in range(max_retries):
            # pick a random node
            node = random.choice(nodes)
            # and get the geomnode for it
            geomnode = node.node()
            # pick a random Geom on the node
            geom = geomnode.getGeom(random.choice(range(geomnode.getNumGeoms())))
            # pick a random primitive (array) on the Geom
            prim = geom.getPrimitive(random.choice(range(geom.getNumPrimitives())))
            # draw an individual primitive (usually a triangle) on the primitive
            num_triangle = random.choice(range(prim.getNumPrimitives()))
            # get the vertex indices referred to by the triangle 
            indices = [prim.getVertex(i) for i in range(prim.getPrimitiveStart(num_triangle),prim.getPrimitiveEnd(num_triangle))]
            # read the position data from the indexed vertices
            vertex_data = geom.getVertexData()
            vertex_reader = GeomVertexReader(vertex_data, 'vertex')
            vertices = []
            transform = node.getMat(scenegraph)
            for i in indices:
                vertex_reader.setRow(i)
                pnt = vertex_reader.getData3f()
                # transform into world space coordinates...
                pnt = transform.xformPoint(pnt)
                vertices.append(pnt)
            # pick a random point on the triangle (uniformly distributed)
            while True:
                a = random.random()
                b = random.random()
                if a+b > 1:
                    continue
                pos = Point3(vertices[0] + (vertices[1]-vertices[0])*a  + (vertices[2]-vertices[0])*b)
                break

            # check if within radius from each point in nearby_to
            if nearby_to and nearby_radius:
                if nearby_param == 'all':
                    accept = True
                    for k in range(len(nearby_to)):
                        p = nearby_to[k]
                        diff = (pos - p)
                        if Point3(diff.getX()/nearby_radius[k].getX(),diff.getY()/nearby_radius[k].getY(),diff.getZ()/nearby_radius[k].getZ()).length() > 1:
                            accept = False
                            break
                    if not accept:
                        nearby_fails += 1
                        continue
                elif nearby_param == 'any':
                    accept = False
                    for k in range(len(nearby_to)):
                        p = nearby_to[k]
                        diff = (pos - p)
                        if Point3(diff.getX()/nearby_radius[k].getX(),diff.getY()/nearby_radius[k].getY(),diff.getZ()/nearby_radius[k].getZ()).length() < 1:
                            accept = True
                            break
                    if not accept:
                        nearby_fails += 1
                        continue
                else: 
                    print "Nearby_param must be 'any' or 'all'"

            # check if within conic constraint regions
            if (within_cone is not None) and (within_cone_angle is not None):
                if within_cone_param == 'all':
                    accept = True
                    for cone in within_cone:
                        diff = Vec3(pos - cone[0])
                        if diff.normalize() and abs(cone[1].angleDeg(diff)) > within_cone_angle/2:
                            accept = False
                            break
                    if not accept:
                        cone_fails += 1
                        continue
                elif within_cone_param == 'any':
                    accept = False
                    for cone in within_cone:
                        diff = Vec3(pos - cone[0])
                        if diff.normalize() and abs(cone[1].angleDeg(diff)) <= within_cone_angle/2:
                            accept = True
                            break
                    if not accept:
                        cone_fails += 1
                        continue
                else:
                    print "Within_cone_param must be 'any' or 'all'"

            # check if box constaints satisfied
            if within_box is not None:
                accept = True
                for axis in [0,1,2]:
                    if pos[axis] < within_box[axis][0] or pos[axis] > within_box[axis][1]:
                        accept = False
                        break
                if not accept:
                    box_fails += 1
                    continue

            # check if outside radius from each point in away_from
            if away_from and away_radius:
                accept = True
                for k in range(len(away_from)):
                    p = away_from[k]
                    diff = (pos - p)
                    if Point3(diff.getX()/away_radius[k].getX(),diff.getY()/away_radius[k].getY(),diff.getZ()/away_radius[k].getZ()).length() < 1:
                        accept = False
                        break
                if not accept:
                    away_fails += 1
                    continue

            # check if the point is invisible from each point in the the given list
            if invisible_from is not None:
                accept = True
                for p in invisible_from:
                    if line_of_sight(physics,src_pos=p,dst_pos=pos,**visibility_params) is not None:
                        accept = False
                        break
                if not accept:
                    visibility_fails += 1
                    continue

            # check if the point is reachable from points in the given list
            if reachable_from is not None:            
                if reachability_param == 'all':
                    accept = True                
                    for p in reachable_from:
                        if not navmesh.is_reachable(pos,p):
                            accept = False
                            break
                    if not accept:
                        reachability_fails += 1
                        continue
                elif reachability_param == 'any':
                    accept = False
                    for p in reachable_from:
                        if navmesh.is_reachable(pos,p):
                            accept = True
                            break
                    if not accept:
                        reachability_fails += 1
                        continue
                else:
                    print "Reachability parameter must be 'any' or 'all'"

            # snap the point to the navmesh
            if navmesh is not None and snap_to_navmesh:
                tmp = navmesh.nearest_point(pos=pos,radius=snap_to_navmesh_radius)
                if output_coord_sys == 'panda':
                    pos = navigation.detour2panda(tmp[1])
                elif output_coord_sys == 'detour':
                    pos = tmp
                else:
                    print "unsupported output coordinate system in generate_positions:",output_coord_sys

            # all checks succeeded: append the pos
            results.append(pos)
            break
        if results:
            print "  generated position within ", retry+1, "attempts."
        else:
            print "  gave up position-generation after ", retry+1, "attempts."
    return results

@livecoding
def generate_path(startpos,                    # the starting position of the path
                  endpos,                      # the end position of the path
                  num_positions,               # the number of positions to generate (between the endpoints)

                  scenegraph,                  # the scene graph for which the positions shall be generated. Positions will be relative to the root node.
                  navmesh=None,                # a navmesh on the scene graph to enforce reachability constraints
                  physics=None,                # a bullet physics world to enforce line-of-sight constraints

                  # placement constraints
                  objectnames=None,                             # the names of objects to whose surfaces the points should be constrained
                  min_distance_between_positions=75,            # the minimum direct distance between any two points on the path (starting point is ignored from 2nd pos onward if too close to endpoint)
                  max_distance_between_successive_positions=150,# the maximum direct distance between two successive points on the path
                  require_reachability=True,                    # only accept paths with reachability between successive points
                  no_successive_line_of_sight=False,            # whether successive points should have no line-of-sight to each other
                  within_box=None,                              # optional overall box constraint for entire path ((minx,maxx),(miny,maxy),(minz,maxz))
                  max_retries=10000,                            # maximum number of attempts at generating a feasible path
                  inner_max_retries=300,                        # maximum number of attempts per generated position
                  z_offset=0.75,                                # offset of the path nodes in z axis
                  ):
    """ Generate a path through a map between two endpoints with pseudo-random intermediate points. """
    for retry in range(max_retries):
        cur_path = [startpos]
        # append nodes...
        for k in range(1,num_positions+1):
            # try to generate a new candidate
            candidate = generate_positions(
                scenegraph=scenegraph,
                navmesh=navmesh,
                physics=physics,
                objectnames=objectnames,
                reachable_from=cur_path[k-1] if require_reachability else None,
                invisible_from=cur_path[k-1] if no_successive_line_of_sight else None,
                away_from=cur_path[1:] if (startpos-endpos).length() < min_distance_between_positions and k>1 else cur_path, # we exclude the startpos from the min-distance constraints if it's too close to the end pos (except for the first path point, where we always respect it)
                nearby_to=[cur_path[k-1],endpos],
                within_box=within_box,
                away_radius=min_distance_between_positions,
                nearby_radius=[max_distance_between_successive_positions,(num_positions-k+1)*max_distance_between_successive_positions],
                max_retries=inner_max_retries)
            if not candidate:
                # unsatisfiable; retry new path
                print "  found unsatisfiable at position " + str(k) + "."
                break
            cur_path.append(candidate[0])
        cur_path.append(endpos)
        if len(cur_path) < num_positions+2:
            # failed to generate path: retry new path
            continue
        # succeeded: return it
        print "  generated path within ", retry+1, "attempts."
        for k in range(len(cur_path)):
            cur_path[k].setZ(cur_path[k].getZ() + z_offset)
        return cur_path
    raise Exception("Failed to generate path through map (check if constraints satisfiable).")


@livecoding
def grid(scr=1,               # 1-based index of the screen (1/2/3)
         x=None,              # tuple of x grid index (1-based) and x grid dimension
         y=None,              # tuple of y grid index (1-based) and y grid dimension
         al='center-center',  # x/y alignment within the cell (string that can contain the words top,bottom,left,right to override the center/center default)
         bo=0.05,             # left/right, top/botton border of each screen, as a fraction of screen height; can be a scalar or a (x,y) tuple
         ma=0.025,            # x/y margin between cells, as a fraction of screen height; can be a scalar or a (x,y) tuple (1/2 margin exists around each cell)
         sys='aspect2d',      # output coordinate system (can be 'render2d', 'aspect2d', 'normalized', or 'window')
         exp=0.0,             # expand the cell size by this value (a fraction of screen height; can be a scalar or a (x,y) tuple)
         mov=0.0,             # movement of the cell position (a fraction of screen height; can be a scalar or a (x,y) tuple)
         ):
    """
    Calculate screen coordinates from positions on a virtual 2d grid on a given screen.
    Supports a border around the edge of the screen, margins between cells and a flexible number of horizontal screens (we use 3 here).
    Can output into various panda3d coordinate systems.
    :return: tuple of (x,y) coordinates or a scalar if just one input coordinate was specified

    Example: grid(1,(1,3),(4,7),al='left')
    --> get coords for 1st screen, on a 3x7 grid, for the cell that's 1st from left and 4th from top, at the left/center wall of the cell (using default margins and screen borders)
    """
    def result(x,y):
        """ Package up the result of this function. """
        if x and y:
            return x,y
        elif x:
            return x
        else:
            return y

    # optional screen shuffling
    scr = screen_shuffle.index(scr)+1

    # parse the alignment string
    if 'left' in al:
        xal = 'left'
    elif 'right' in al:
        xal = 'right'
    else:
        xal = 'center'
    if 'top' in al:
        yal = 'top'
    elif 'bottom' in al:
        yal = 'bottom'
    else:
        yal = 'center'

    # parse border
    if type(bo) is tuple or type(bo) is list and len(bo)==2:
        xbo = bo[0]
        ybo = bo[1]
    else:
        xbo = bo
        ybo = bo

    # parse margin
    if type(ma) is tuple or type(ma) is list and len(ma)==2:
        xma = ma[0]
        yma = ma[1]
    else:
        xma = ma
        yma = ma

    # parse expansion
    if type(exp) is tuple or type(exp) is list and len(exp)==2:
        xexp = exp[0]
        yexp = exp[1]
    else:
        xexp = exp
        yexp = exp

    # parse cell movement
    if type(mov) is tuple or type(mov) is list and len(mov)==2:
        xmov = mov[0]
        ymov = mov[1]
    else:
        xmov = mov
        ymov = mov

    # parse x/y
    if x:
        xg = x[1]   # x grid dim
        x = x[0]    # x grid pos
    else:
        xg = None
    if y:
        yg = y[1]   # y grid dim
        y = y[0]    # y grid pos
    else:
        yg = None

    aspect = screen_aspect

    # rescale all height-relative parameters to be aspect-correct
    xbo /= aspect
    xma /= aspect
    xexp /= aspect
    xmov /= aspect
    if xg:
        xma /= (1.0/float(xg) * (1.0/len(screen_shuffle) - 2*xbo))
    if yg:
        yma /= (1.0/float(yg) * (1.0 - 2*ybo))

    # calc relative offset within the cell
    if xal == 'left':
        x_off = xma/2.0
    elif xal == 'center':
        x_off = 0.5
    elif xal == 'right':
        x_off = 1.0 - xma/2.0
    else:
        raise Exception('Unknown x alignment value: ' + xal)
    if yal == 'top':
        y_off = yma/2.0
    elif yal == 'center':
        y_off = 0.5
    elif yal == 'bottom':
        y_off = 1.0 - yma/2.0
    else:
        raise Exception('Unknown y alignment value: ' + yal)

    # calculate normalized coordinates for top/left origin coordinate system
    nx = xbo + (scr-1)*2*xbo + (scr-1 + (x-1 + x_off)/float(xg)) * (1.0/len(screen_shuffle) - 2*xbo) if x else None
    ny = ybo + ((y-1 + y_off)/float(yg))*(1.0-2*ybo) if y else None
    if not (nx or ny):
        raise Exception('At least one coordinate must be specified.')

    # apply cell expansion
    if ny and yexp and not yal == 'center':
        ny += -yexp if yal == 'top' else yexp
    if nx and xexp and not xal == 'center':
        nx += -xexp if xal == 'left' else xexp

    # apply cell movement
    if ny and ymov:
        ny += ymov
    if nx and xmov:
        nx += xmov

    # convert into window coordinates (bottom/left)
    if ny:
        ny = 1.0-ny
    if sys == 'window':
        return result(nx,ny)

    # convert into render2d coordinates
    rx = 2*nx - 1 if nx else None
    ry = 2*ny - 1 if ny else None
    if sys == 'render2d':
        return result(rx,ry)

    # convert into aspect2d coordinates
    ax = rx*aspect if rx else None
    ay = ry if ry else None
    if sys == 'aspect2d':
        return result(ax,ay)

    raise Exception('Unknown coordinate system: ' + sys)


# =========================================
# === EXPERIMENT SUBTASK INFRASTRUCTURE ===
# =========================================

class ScoreCounter(BasicStimuli):
    """
    Logs the per-client score and does all the reward notification things (counts the score and plays sounds when the score is to be updated).
    It maintains a special failure condition, which is reached when the score goes below a certain level, and is only recovered when the score goes
    back above a certain (usually higher) level -- this allows us to lock down other tasks if a subject if failing on a particular task.
    """

    def __init__(self,
                 stimpresenter,                       # a (possibly remote) instance of BasicStimuli to present the (reward) sound stimuli (or None for local)
                 score_log,                           # the score log file to write to
                 counter_name,                        # name of this score counter (in the logfile and markers)
                 client_idx,                          # index of the affected participant

                 # scoring parameters
                 initial_score=50,                    # the initial score
                 fail_level=0,                        # falling below this level puts the score logic in "failure" mode, where it stays...
                 critical_level=25,                   # ... until the player gets over the critical level again (note: fail_level can be set to a low negative value to effectively disable it)
                 maximum_level=100,                   # this is the highest level that can be graphically indicated

                 # display parameters
                 bar_rect = (-0.3,0.3,-0.7,-0.9),     # rectangle for the score display bar
                 bar_background_color = (0,0,0,1),    # background color of the score bar
                 bar_failure_color = (1,0,0,1),       # the color of the indicator when in failure mode (has hit the fail level and not yet exceeded critical again)
                 bar_critical_color = (1,1,0,1),      # the color of the indicator when below the critical mark but not in failure mode
                 bar_fine_color = (0,1,0,1),          # the color of the bar when above the critical mark
                 bar_abovemax_color = (0,0,1,1),      # the color of the bar when above the maximum
                 font_size = 4,                       # font size of the score text
                 text_color = (0.65,0.65,1,1),        # color of the score text itself
                 text_color_negative = (1,0,0,1),     # color of the score text when negative
                 bar_vertical_squish = 0.5,           # squishes the bar vertically...

                 # sound parameters
                 sound_params = None,                 # properties of the score response sound (dictionary of parameters to the sound() command)
                 gain_file = 'default_ding.wav',      # sound file per point
                 loss_file = 'default_buzz.wav',      # sound file for losses
                 none_file = 'default_click.wav',     # file to play if no reward
                 failure_file = 'failure.wav',        # file to play if player fails this score counter (hits 0)
                 recovery_file = 'recovery.wav',      # file to play if player makes it back into the green with this counter (goes above critical mark) [should play the triumphal American marsh in Civ II]
                 ding_interval = 0.1,                 # interval at which successive gain sounds are played... (if score is > 1)
                 ding_granularity=1,                  # the number of dings played is ceil(scoredelta/ding_granularity); same holds for buzzes
                 loss_volume = 0.5,                   # volume of the loss sound
                 gain_volume = 0.5,                   # volume of the gain sound
                 failure_volume = 0.5,                # volume of the failure sound
                 recovery_volume = 0.5,               # volume of the recovery sound

                 # rising score number (currently unused)
                 riser_pos = None,                    # initial pos of the riser
                 riser_updrift = 0.1,                 # updrift in units/second
                 riser_color = ((0.2,1,0.2,1),(1,0.2,0.2,1)), # initial colors of the riser (bonus,penalty)
                 riser_fade = -0.1,                   # value added to the opacity per second
                 riser_fontsize = 5,                  # font size of the text

                 dependent_score = None               # optionally a dependent score counter that shall aslo be updated
                 ):
        BasicStimuli.__init__(self)
        if not sound_params:
            sound_params = {'direction': 0.0}
        self._stimpresenter = stimpresenter if stimpresenter is not None else self

        self.score_log = score_log
        self.counter_name = counter_name
        self.client_idx = client_idx

        self.score = initial_score
        self.fail_level = fail_level
        self.critical_level = critical_level
        self.maximum_level = maximum_level

        self.bar_rect = list(bar_rect)
        # apply vertical squish
        midpoint = (self.bar_rect[2]+self.bar_rect[3])/2
        self.bar_rect[2] = midpoint + (self.bar_rect[2] - midpoint)*bar_vertical_squish
        self.bar_rect[3] = midpoint + (self.bar_rect[3] - midpoint)*bar_vertical_squish

        self.bar_background_color = bar_background_color
        self.bar_failure_color = bar_failure_color
        self.bar_critical_color = bar_critical_color
        self.bar_fine_color = bar_fine_color
        self.bar_abovemax_color = bar_abovemax_color

        self.font_size = font_size
        self.text_color = text_color
        self.text_color_negative = text_color_negative

        self.sound_params = sound_params
        self.gain_file = gain_file
        self.loss_file = loss_file
        self.none_file = none_file
        self.failure_file = failure_file
        self.recovery_file = recovery_file
        self.ding_interval = ding_interval
        self.ding_granularity = ding_granularity 
        self.loss_volume = loss_volume
        self.gain_volume = gain_volume
        self.failure_volume = failure_volume
        self.recovery_volume = recovery_volume

        self.riser_pos = ((self.bar_rect[0]+self.bar_rect[1])/2,(self.bar_rect[2]+self.bar_rect[3])/2) if riser_pos is None else riser_pos
        self.riser_updrift = riser_updrift
        self.riser_color = riser_color
        self.riser_fade = riser_fade
        self.riser_fontsize = riser_fontsize

        self.dependent_score = dependent_score

        self.paused = False
        self._is_failure = False

        # open the score log
        self.marker('Experiment Control/Task/Scoring/Initial/%i Points, Experiment Control/Task/Scoring/Counter/%s, Participant/ID/%i' % (self.score, self.counter_name, self.client_idx))
        self.score_log.write('%s %s [player %i]: score -> %i (new session)\n' % (time.asctime(),self.counter_name,self.client_idx,self.score))
        self.init_graphics()


    def __del__(self):
        self._bar_background.destroy()
        self._bar_indicator.destroy()
        self._text.destroy()
        self._bar_scaler.removeNode()

    def is_failure(self):
        """ Whether the subject is currently in "failure" mode with this score counter. Other tasks may be "blocked" while in this state. """
        return self._is_failure

    @livecoding
    def score_event(self,
                    delta,              # relative score (can be negative)
                    nosound=True):      # if true, the ding/buzz sounds are disabled -- the critical sounds (failure/recovery) are unaffected by this
        """ Handle a score update. """
        if self.paused:
            return
        self.marker('Stimulus/Feedback/%s/%i Points, Experiment Control/Task/Scoring/Counter/%s, Participant/ID/%i' % ('Reward' if delta>0 else 'Penalty', delta, self.counter_name, self.client_idx))
        self.score_log.write('%s %s [player %i]: score %i+%i -> %i\n' % (time.asctime(),self.counter_name,self.client_idx,self.score,delta,self.score+delta))
        self.score = self.score+delta
        # failure condition
        if self.score <= self.fail_level and not self._is_failure:
            self._is_failure = True
            self.play_failure()
        if self.score >= self.critical_level and self._is_failure:
            self._is_failure = False
            self.play_recovery()
        # display
        if not nosound:
            self.play_delta_sounds(delta)
        self.update_graphics()
        # handle dependent counters
        if self.dependent_score:
            self.dependent_score.score_event(delta,nosound=True)

    # === graphics code ===

    @livecoding
    def init_graphics(self):
        # use a regular rectangle for the bar's background
        self._bar_background = self._stimpresenter.rectangle(rect=tuple(self.bar_rect),duration=max_duration,block=False,color=self.bar_background_color,depth=-0.1)
        # use another rectangle for the bar indicator
        col = self.cur_color()
        self._bar_indicator = rpyc.enable_async_methods(self._stimpresenter.rectangle(rect=(0,self.bar_rect[1]-self.bar_rect[0],self.bar_rect[2],self.bar_rect[3]),duration=max_duration,block=False,color=(0,0,0,0),depth=0.1))
        # but make the rectangle a child of a scaler node (that we use to scale the bar)
        self._bar_scaler = rpyc.enable_async_methods(self._stimpresenter._engine.base.aspect2d.attachNewNode('bar_scaler_' + self.counter_name))
        self._bar_scaler.setPos(self.bar_rect[0],0,0)
        self._bar_scaler.setScale(max(0.0,min(1.0,self.score/float(self.maximum_level))),1,1)
        self._bar_indicator.reparentTo(self._bar_scaler)
        self._bar_indicator.setColor(col[0],col[1],col[2],col[3])
        self._text = rpyc.enable_async_methods(self._stimpresenter.write(self.counter_name + ':' + str(self.score),duration=max_duration,block=False,pos=((self.bar_rect[0]+self.bar_rect[1])/2,(self.bar_rect[2]+self.bar_rect[3])/2),fg=self.text_color))

    @livecoding
    def update_graphics(self):
        """ Update the graphics of the score counter. """
        col = self.cur_color()
        self._bar_indicator.setColor(col[0],col[1],col[2],col[3])
        self._bar_scaler.setScale(max(0.0,min(1.0,self.score/float(self.maximum_level))),1,1)
        self._text.setText(self.counter_name + ': ' + str(self.score))
        if self.score <= 0:
            self._text.setFg((self.text_color_negative[0],self.text_color_negative[1],self.text_color_negative[2],self.text_color_negative[3]))
        else:
            self._text.setFg((self.text_color[0],self.text_color[1],self.text_color[2],self.text_color[3]))

    def cur_color(self):
        """ Calculate the current bar color. """
        if self.score >= self.maximum_level:
            col = self.bar_abovemax_color
        elif self.score >= self.critical_level:
            col = self.bar_fine_color
        elif self._is_failure:
            col = self.bar_failure_color
        else:
            col = self.bar_critical_color
        return col

    # === sound code ===

    @livecoding
    def play_delta_sounds(self,delta):
        """ Issue the sound feedback associated with a score event. """
        if delta>0:
            # play k gain sound events for a score delta of k
            self.marker(1)
            taskMgr.doMethodLater(0,self.play_gain,'Score sound')
            while delta > self.ding_granularity:
                taskMgr.doMethodLater(delta*self.ding_interval,self.play_gain,'Score sound')
                delta -= self.ding_granularity
        elif delta<0:
            # play k loss sound events for a score delta of -k
            self.marker(2)
            taskMgr.doMethodLater(0,self.play_loss,'Score sound')
            while delta < -self.ding_granularity:
                taskMgr.doMethodLater(-delta*self.ding_interval,self.play_loss,'Score sound')
                delta += self.ding_granularity
        else:
            # play the no-score delta sounds (probably unused)
            rpyc.async(self._stimpresenter.sound)(self.none_file,volume=self.loss_volume,**self.sound_params)

    @livecoding
    def play_gain(self,task):
        """ Play the gain sound. """
        rpyc.async(self._stimpresenter.sound)(self.gain_file,volume=self.gain_volume,**self.sound_params)
        self.marker('Stimulus/Auditory/Reward, Stimulus/Auditory/Sound File/"%s", Participant/ID/%i' % (self.gain_file, self.client_idx))
        return task.done

    @livecoding
    def play_loss(self,task):
        """ Play the loss sound. """
        rpyc.async(self._stimpresenter.sound)(self.loss_file,volume=self.loss_volume,**self.sound_params)
        self.marker('Stimulus/Auditory/Penalty, Stimulus/Auditory/Sound File/"%s", Participant/ID/%i' % (self.loss_file, self.client_idx))
        return task.done

    @livecoding
    def play_failure(self):
        """ Play the failure sound. """
        rpyc.async(self._stimpresenter.sound)(self.failure_file,volume=self.failure_volume,**self.sound_params)
        self.marker('Stimulus/Auditory/Failure, Stimulus/Auditory/Sound File/"%s", Experiment Control/Task/Scoring/Counter/%s, Participant/ID/%i' % (self.failure_file, self.counter_name, self.client_idx))

    @livecoding
    def play_recovery(self):
        """ Play the recovery sound. """
        rpyc.async(self._stimpresenter.sound)(self.recovery_file,volume=self.recovery_volume,**self.sound_params)
        self.marker('Stimulus/Auditory/Recovery, Stimulus/Auditory/Sound File/"%s", Experiment Control/Task/Scoring/Counter/%s, Participant/ID/%i' % (self.recovery_file, self.counter_name, self.client_idx))


_question_id_generator = itertools.count(1)   # a generator to assign experiment-wide unique id's to questions asked to the subject
class StimulusQuestion(object):
    """
    Small utility class that encapsulates a probe/query about a stimulus (for example, about the shape, color, etc.).
    """

    def __init__(self,
                 client_idx,                    # id of the responsible participant
                 category,                      # category of the question (e.g., "shape")
                 phrase,                        # wording of the question
                 correct_answer,                # correct answer for the question
                 all_answers,                   # list of all possible answers for this question category
                 label,                         # label of the stimulus

                 identifier=None,               # unique numeric identifier of the question (auto-generated if None)
                 implicit_creation_marker=True, # whether to emit a marker upon creation of the question object
                 implicit_removal_marker=False, # whether to emit a marker upon removal of the question object
    ):
        self.category = category
        self.phrase = phrase
        self.correct_answer = correct_answer
        self.all_answers = all_answers
        self.label = label
        self.client_idx = client_idx
        self.identifier = next(_question_id_generator) if identifier is None else identifier

        self.implicit_removal_marker = implicit_removal_marker
        if implicit_creation_marker:
            self.creation_marker()

    def __del__(self):
        if self.implicit_removal_marker:
            self.discard_marker()

    def creation_marker(self):
        """ Issue a marker associated with the creation of this question. """
        send_marker('Experiment Control/Task/Queries/Create/{category:%s|phrase:"%s"|correct_answer:%s|all_answers:%s|label:%s|identifier:%i}, Participant/ID/%i' %
                    (self.category,self.phrase,self.correct_answer,self.all_answers,self.label,self.identifier,self.client_idx))

    def issue_marker(self):
        """ Issue a marker associated with the presentation of this question. """
        send_marker('Experiment Control/Task/Queries/Issue/{identifier:%i}, Participant/ID/%i' % (self.identifier,self.client_idx))

    def discard_marker(self):
        """ Issue a marker associated with discarding this question (potentially unused). """
        send_marker('Experiment Control/Task/Queries/Discard/{identifier:%i}, Participant/ID/%i' % (self.identifier,self.client_idx))



class QueryPresenter(LatentModule):
    """
    This class handles the presentation of query (i.e., question) stimuli associated with a particular event.
    The basic idea is that different events in different contexts can submit a probe stimulus.
    In the case of multiple queries coming in near-simultaneously, the later probe will be dropped
    (if within the lock duration of the former probe).
    """

    def __init__(self,
                 # output environment
                 presenterfuncs,                            # where to present the queries: this is a map of the form {'querydomain',presenterfunc, 'querydomain',presenterfunc, ...}
                 clearfuncs,                                # functions to clear the respective presenters
                 # which covers multiple domains (e.g., auditory and visual modalities and associated presenters)
                 # the presenterfuncs are MessagePresenter.submit()-like functions
                 scorecounters,                             # where to add score: this is a map of the form {'scoredomain',scorecounter, 'scoredomain',scorecounter, ...}
                 client_idx,                                # the ID of the affected subject
                 stimpresenter,                             # an instance of BasicStimuli to present the sound stimuli (or None if local)

                 # timing parameters
                 default_response_timeout = 4,              # default response timeout...
                 default_lock_duration = (4,5),             # the default duration for which the probe presenter is locked ([minimum,maximum]), in seconds
                 default_onset_delay = 0,                   # the default onset delay for the queries (in seconds)

                 # scoring parameters
                 default_loss_incorrect=-2,                 # amount of loss incurred when incorrectly answering
                 default_gain_correct=1,                    # amount of reward gained when answering correctly
                 default_loss_skipped=-1,                   # amount of loss incurred when admitting a miss
                 default_loss_missed=-2,                    # amount of loss incurred when missing the question (and basically the sentence, too)

                 # response event parameters
                 default_skip_response = 'skip',            # response event to indicate that a probe should be skipped
                 default_event_prefix = '',                 # the prefix that is assumed to come before any event
                 default_query_prefix = '',                 # the prefix that is assumed to come before any query

                 # task-specific sounds
                 miss_sound = 'fail-buzzer-02.wav',         # sound to play when the subject misses a query
                 miss_volume = 0.0,                         # volume of the miss sound

                 # skipped a response
                 skip_sound = 'KenbeepSoft.wav',            # sound to play whens the subject slick skip
                 skip_volume = 0.5,                         # volume of the skip sound
                 ):

        LatentModule.__init__(self)
        self.stimpresenter = stimpresenter if stimpresenter is not None else self
        self.presenterfuncs = presenterfuncs
        self.clearfuncs = clearfuncs
        self.scorecounters = scorecounters

        self.default_response_timeout = default_response_timeout
        self.default_lock_duration = default_lock_duration
        self.default_onset_delay = default_onset_delay
        self.default_loss_incorrect = default_loss_incorrect
        self.default_gain_correct = default_gain_correct
        self.default_loss_skipped = default_loss_skipped
        self.default_loss_missed = default_loss_missed
        self.default_skip_response = default_skip_response
        self.default_event_prefix = default_event_prefix
        self.default_query_prefix = default_query_prefix
        self.client_idx = client_idx
        self.miss_sound = miss_sound
        self.skip_sound = skip_sound
        self.skip_volume = skip_volume
        self.miss_volume = miss_volume

        self._locked_until = 0


    def submit_question(self,
                        question,  # the question object to submit
                        **kwargs   # other arguments to submit()
                        ):
        """ Submit a question object. This is a convenience function. """
        self.submit(query=question.phrase, expected_response=question.correct_answer, wrong_responses=list(set(question.all_answers) - set([question.correct_answer])),
            query_id=question.identifier, **kwargs)

    def submit(self,**kwargs):
        """
        Submit a new query. Returns true if placed successfully, otherwise false.
        See _submit() for the argument list and defaults.
        """
        if 'onset_delay' in kwargs:
            onset_delay = kwargs['onset_delay']
        else:
            onset_delay = self.default_onset_delay
        if onset_delay > 0:
            pass
            taskMgr.doMethodLater(onset_delay, lambda task: self._submit(**kwargs), 'QueryPresenter._submit()')
        else:
            self._submit(**kwargs)

    #noinspection PyUnusedLocal
    @livecoding
    def _submit(self,
                query,                       # the query message to present
                expected_response,           # the correct response event for this particular query
                wrong_responses,             # a list of incorrect response events for this particular query
                querydomain,                 # the domain in which the query should be placed (refers to the presenterfuncs map)
                scoredomain,                 # the domain in which the score should be counted (refers to the scorecounters map)
                query_id,                    # id of the query (to link it to the associated stimulus)
                skip_response=None,          # the response to skip the query
                lock_duration=None,          # for how long the presenter is going to be blocked if the query was placed successfully
                response_timeout=None,       # the timeout within which the query must be responded to
                onset_delay=None,            # an onset delay for the query (e.g., to wipe the content from short-term memory)
                loss_incorrect=None,         # scores for various situations
                gain_correct=None,
                loss_skipped=None,
                loss_missed=None,
                focused=True,                # whether this query belongs to an event that was supposed to be focused (otherwise no score consequences)
                no_queryprefix=False         # whether to disable the query prefix (if any)
                ):
        """ The internal query-submission function that does the actual work. """

        # apply defaults to response codes
        if skip_response is None:
            skip_response = self.default_skip_response
        if type(wrong_responses) is not list:
            wrong_responses = [wrong_responses]
        expected_response = self.default_event_prefix + expected_response
        wrong_responses = [self.default_event_prefix + ev for ev in wrong_responses]
        skip_response = self.default_event_prefix + skip_response
        # apply defaults to locking
        if lock_duration is None:
            lock_duration = self.default_lock_duration
        if response_timeout is None:
            response_timeout = self.default_response_timeout
        # apply defaults to score aspects
        if loss_incorrect is None:
            loss_incorrect= self.default_loss_incorrect
        if gain_correct is None:
            gain_correct = self.default_gain_correct
        if loss_skipped is None:
            loss_skipped = self.default_loss_skipped
        if loss_missed is None:
            loss_missed = self.default_loss_missed

        now = time.time()
        if now > self._locked_until:
            # call the presenter to present the query
            if type(lock_duration) == list or type(lock_duration) == tuple:
                lock_duration = random.uniform(lock_duration[0],lock_duration[1])
            self._locked_until = time.time()+lock_duration
            funcs = self.presenterfuncs[querydomain]
            for f in funcs:
                f(('' if no_queryprefix else self.default_query_prefix) + query,lockduration=lock_duration)
            self.marker('Experiment Control/Task/Queries/Issue-%s/{identifier:%i}, Participant/ID/%i' % ('Focused' if focused else 'Nonfocused',query_id,self.client_idx))
            if focused:
                # watch for a response event
                watcher = EventWatcher.EventWatcher()
                event_list = [expected_response]+wrong_responses+[skip_response]
                print str(time.time()) + ": now watching for response; timeout is " + str(response_timeout)
                watcher.watch_for(
                    eventtype=event_list,
                    handler=(lambda eventtype,timepoint: self.on_response(
                        eventtype,expected_response,wrong_responses,skip_response,loss_incorrect,gain_correct,loss_skipped,query_id,scoredomain,querydomain)),
                    handleduration=response_timeout,
                    timeouthandler=lambda: self.on_timeout(loss_missed,query_id,scoredomain,querydomain))

    @livecoding
    def on_response(self,actual_response,correct_response,wrong_responses,skip_response,loss_incorrect,gain_correct,loss_skipped,query_id,scoredomain,querydomain):
        """ Function that is called when a subject makes a timely response to a query."""
        if actual_response == correct_response:
            self.marker('Experiment Control/Task/Correct Action/%s, Experiment Control/Task/Queries/Response/{identifier:%i}, Participant/ID/%i' % (actual_response,query_id,self.client_idx))
            self.scorecounters[scoredomain].score_event(gain_correct,nosound=False)
        elif actual_response in wrong_responses:
            self.marker('Experiment Control/Task/Incorrect Action/%s, Experiment Control/Task/Queries/Response/{identifier:%i}, Participant/ID/%i' % (actual_response,query_id,self.client_idx))
            self.scorecounters[scoredomain].score_event(loss_incorrect,nosound=False)
        elif actual_response == skip_response:
            self.marker('Experiment Control/Task/Skipped Action, Experiment Control/Task/Queries/Response/{identifier:%i}, Participant/ID/%i' % (query_id,self.client_idx))
            rpyc.async(self.stimpresenter.sound)(self.skip_sound,volume=self.skip_volume,block=False)
            self.scorecounters[scoredomain].score_event(loss_skipped)
        else:
            self.marker('Experiment Control/Task/Inappropriate Action/%s, Experiment Control/Task/Queries/Response/{identifier:%i}, Participant/ID/%i' % (actual_response,query_id,self.client_idx))
            self.scorecounters[scoredomain].score_event(loss_incorrect)
        # clear the respective presenter
        for f in self.clearfuncs[querydomain]:
            f()

    @livecoding
    def on_timeout(self,loss_missed,query_id,scoredomain,querydomain):
        """ Function that is called when a subset fails to make a timely response to a query. """
        self.marker('Experiment Control/Task/Missed Action, Experiment Control/Task/Queries/Response/{identifier:%i}, Participant/ID/%i' % (query_id,self.client_idx))
        self.scorecounters[scoredomain].score_event(loss_missed)
        rpyc.async(self.stimpresenter.sound)(self.miss_sound,volume=self.miss_volume,block=False)
        # clear the respective presenter
        for f in self.clearfuncs[querydomain]:
            f()


class AttentionSetManager(LatentModule):
    """
    This class manages the scheduling of the current attention set (e.g., {visual,auditory}), presents the appropriate notification stimuli and updates
    a permanent display of the currently active set.
    """

    def __init__(self,
                 client_idx,    # identifier of the responsible participant
                 client_id,     # callsign of the responsible participant
                 regions,       # a dictionary of all attention regions and associated focusable objects, of the form: {'visual',[my_visual_focusable_obj1,my_visual_focusable_obj2], 'auditory',[my_auditory_focusable_obj], ...}
                                # each of these objects has a .focused property which governs how the object behaves, in particular how it assigns scores (e.g., a non-focused object would not assign minus points for missed responses)
                                # alternatively each of these objects can be a two-element tuple of functions to invoke, where the first is used to defocus and the second is used to set focus
                 instructors,   # a dictionary of all attention regions and associated instruction presenter functions, of the form: {'visual',[my_instruction_presenter1,my_instruction_presenter2], 'auditory',[my_instruction_presenter3], ...}
                                # these are used to generate top-down switch cues
                 indicators,    # a dictionary of all attention regions and associated activity indicator functions, of the form: {'visual',[disable_function,enable_function], 'auditory',[disable_function,enable_function], ...}
                 load_distribution = lambda: random.choice([0,1,1,1,1,1,1,1,2,2]),  # a function that samples the current number of concurrent modalities from a discrete distribution
                 maintenance_duration = lambda: random.uniform(30,60),              # a function that samples the duration for which the current attention set shall be maintained, in seconds
                 available_subset = None,                                           # optionally a subset of currently available region names (list)
                 blink_count = 4,                                                   # number of blinks performed the attention indicators when they come on
                 blink_duration = 0.75,                                             # duration of the blinks (on state & off state, respectively)
                 skip_duplicate_instructors = [('sounds','spoken sentences')]       # a list of pairs of instructors that are duplicate: if both are in the list (for a particular instruction), remove the second one from that list (e.g. two voice channels)
    ):
        LatentModule.__init__(self)
        self.client_idx = client_idx
        self.client_id = client_id
        self.regions = regions
        self.instructors = instructors
        self.indicators = indicators
        self.load_distribution = load_distribution
        self.maintenance_duration = maintenance_duration
        self.region_names = self.regions.keys()
        self.available_subset = self.region_names
        self.blink_count = blink_count
        self.blink_duration = blink_duration
        self.active_regions = []                            # currently active regions
        self.prev_active_regions = []                       # previously active regions
        self.load_distribution_override = None              # can override the current allowed load distribution
        self.skip_duplicate_instructors = skip_duplicate_instructors

        self.mask_regions(available_subset)                 # apply the region mask

    def run(self):
        if self.available_subset is None:
            self.available_subset = self.region_names
        self.log_setup_parameters()

        # start with a half-length lull period
        self.sleep(self.maintenance_duration()/2)

        while True:
            # determine the number of concurrent regions
            if self.load_distribution_override is not None:
                num_regions = self.load_distribution_override()
            else:
                num_regions = self.load_distribution()

            # wait until the available subset is not empty (any more)
            while len(self.available_subset) == 0:
                self.sleep(5)

            # randomly draw this many active regions from self.regions
            self.active_regions = random.sample(set(self.available_subset).intersection(set(self.regions.keys())),min(num_regions,len(self.available_subset)))
            self.marker('Experiment Control/Task/Attention/Switch To/%s, Participant/ID/%i' % (str(self.active_regions).replace(',','|'),self.client_idx))

            # set the focused flag for all focusable objects appropriately
            for regionname in self.region_names:
                if regionname in self.active_regions:
                    for focusable in self.regions[regionname]:
                        if type(focusable) is tuple:
                            focusable[1]()
                        else:
                            focusable.focused = True
                else:
                    for focusable in self.regions[regionname]:
                        if type(focusable) is tuple:
                            focusable[0]()
                        else:
                            focusable.focused = False

            # display the switch instructions in the appropriate instructors
            if len(self.active_regions) == 0:
                switch_message = self.client_id + ', starting now, ignore all side tasks and focus on the main mission.'
            else:
                switch_message = self.client_id + ', starting now, your side tasks are the ' + self.active_regions[0]
                if len(self.active_regions) > 1:
                    for r in self.active_regions[1:]:
                        switch_message += ' and the ' + r
                switch_message += '.'
            # remove potential duplicates from the output channels
            instruct_via = self.prev_active_regions
            for potential_duplicate in self.skip_duplicate_instructors:
                if potential_duplicate[0] in instruct_via and potential_duplicate[1] in instruct_via:
                    instruct_via.remove(potential_duplicate[1])
            # now output on all that remain
            for regionname in instruct_via:
                self.instructors[regionname](switch_message)

            # update the visibility of the region activity indicators
            try:
                # fade out the now unfocused regions
                now_unfocused = set(self.prev_active_regions).difference(set(self.active_regions))
                self.fade_indicators(1,0,self.blink_duration,now_unfocused)
                # fade in the now focused regions
                now_focused = set(self.active_regions).difference(set(self.prev_active_regions))
                print "Client",self.client_idx,", active: ",self.active_regions
                self.fade_indicators(0,1,self.blink_duration,now_focused)
                # fade out and back in for a few times
                for k in range(self.blink_count):
                    self.fade_indicators(1,0,self.blink_duration,now_focused)
                    self.fade_indicators(0,1,self.blink_duration,now_focused)
                # ensure that everything is in the correct visibility state
                for regionname in self.active_regions:
                    self.indicators[regionname](1)
                for regionname in set(self.region_names).difference(set(self.active_regions)):
                    self.indicators[regionname](0)
            except Exception as e:
                print e
                traceback.print_exc()
                send_marker('Experiment Control/Status/Error/%s' % (str(e),))

            self.sleep(self.maintenance_duration() - 2*self.blink_duration*self.blink_count)
            self.prev_active_regions = self.active_regions

    def fade_indicators(self,from_val,to_val,duration,region_subset):
        """ Fade a subset of attention indicators in or out. """
        tstart = time.time()
        tend = tstart + duration
        while True:
            now = time.time()
            visibility = smoothstep((now-tstart)/duration,from_val,to_val)
            for regionname in region_subset:
                self.indicators[regionname](visibility)
            if now > tend:
                break
            self.sleep(0.05)
        # ensure that they have the correct final value
        for regionname in region_subset:
            self.indicators[regionname](to_val)


    def mask_regions(self,mask):
        """ Apply a mask of possible active regions. """
        if mask is None:
            return
        self.available_subset = mask
        for r in self.region_names:
            if r in mask:
                if r in self.active_regions:
                    # enabled
                    self.indicators[r](1)
                    # focused
                    for focusable in self.regions[r]:
                        try:
                            if type(focusable) is tuple:
                                focusable[1]()
                            else:
                                focusable.focused = True
                        except:
                            print "Could not set unfocused state during region mask (" + r +")"
                else:
                    # disabled
                    self.indicators[r](0)
                    # not focused
                    for focusable in self.regions[r]:
                        try:
                            if type(focusable) is tuple:
                                focusable[0]()
                            else:
                                focusable.focused = False
                        except:
                            print "Could not set unfocused state during region mask (" + r +")"
            else:
                # not visible
                self.indicators[r](0)
                # not focused
                try:
                    for focusable in self.regions[r]:
                        if type(focusable) is tuple:
                            focusable[0]()
                        else:
                            focusable.focused = False
                except:
                    print "Could not set unfocused state during region mask (" + r +")"
        print "Client",self.client_idx,", mask: ",self.available_subset

# ===============================
# === SUBTASK IMPLEMENTATIONS ===
# ===============================

class StressTask(LatentModule):
    """
    Modulates a stress parameter according to a schedule (switches between low and high levels) and
    updates an indicator icon & sound when the level switches.
    Has no effects by itself but the scores associated with several tasks use the stress level as multiplier
    for penalties and rewards.
    """

    def __init__(self,
                 iconpresenterfunc,                                     # presenter function to display the stress indicator icon
                 client_idx,                                            # index of the affected participant
                 low_stress_duration = lambda: random.uniform(60,360),  # the duration of low-stress periods, in seconds
                 high_stress_duration = lambda: random.uniform(15,60),  # the duration of high-stress periods, in seconds
                 low_stress_value = 1,                                  # the stress parameter value during low periods
                 high_stress_value = 3,                                 # the stress parameter value during high periods
                 low_transition_sound = 'birds.wav',                    # sound to play when transitioning to low stress
                 low_transition_icon = 'lowstress.png',                 # sound to play when transitioning to low stress
                 low_transition_volume = 0.3,                           # volume of that sound
                 high_transition_sound = 'heartbeat.wav',               # sound to play when transitioning to high stress
                 high_transition_icon = 'highstress.png',               # sound to play when transitioning to high stress
                 high_transition_volume = 0.3,                          # volume of that sound
                 stimpresenter = None,                                  # an instance of BasicStimuli to present the sound events                  
                 ):
        LatentModule.__init__(self)
        self.stimpresenter = stimpresenter if stimpresenter is not None else self 
        self.iconpresenterfunc = iconpresenterfunc 
        self.low_stress_duration = low_stress_duration  
        self.high_stress_duration = high_stress_duration  
        self.low_stress_value = low_stress_value
        self.high_stress_value = high_stress_value
        self.low_transition_sound = low_transition_sound  
        self.high_transition_sound = high_transition_sound  
        self.low_transition_icon = low_transition_icon
        self.high_transition_icon = high_transition_icon  
        self.low_transition_volume = low_transition_volume
        self.high_transition_volume = high_transition_volume  
        self.client_idx = client_idx

        # this is the stress parameter
        self.stress_level = low_stress_value

        self.disabled = False    # whether the task is temporarily disabled

    def run(self):
        self.log_setup_parameters()
        while True:
            # enter a low stress period
            rpyc.async(self.stimpresenter.sound)(filename = self.low_transition_sound, volume = self.low_transition_volume)
            self.iconpresenterfunc(self.low_transition_icon)
            self.stress_level = self.low_stress_value
            duration = self.low_stress_duration()
            self.marker('State/Stress Level/%f, Participant/ID/%i' % (self.stress_level,self.client_idx))
            self.sleep(duration)

            if self.disabled:
                while self.disabled:
                    # do not enter a high-stres period while we're still disabled
                    self.sleep(1)
                # and generally skip forward to the slow-stress period after the pause
                continue

            # enter a high stress period
            rpyc.async(self.stimpresenter.sound)(filename = self.high_transition_sound, volume = self.high_transition_volume)
            self.iconpresenterfunc(self.high_transition_icon)
            self.stress_level = self.high_stress_value
            duration = self.high_stress_duration()
            self.marker('State/Stress Level/%f, Participant/ID/%i' % (self.stress_level,self.client_idx))
            self.sleep(duration)            







class IndicatorLightTask(LatentModule):
    """
    A relatively configurable indicator light class that can sporadically turn on/off or stop blinking.
    Demands a response that can be configured (press a button when turning on / turning off / stopping to blink).
    """
    def __init__(self,
                 # general properties
                 scorecounter,                                  # reward handling logic
                 stimpresenter,                                 # an instance of BasicStimuli that should present the sound stimuli (local if None)
                 client_idx,                                    # index of the responsible participant

                 event_interval=lambda: random.uniform(45,85),  # interval between two successive events
                 focused = True,                                # whether this task is currently focused

                 # graphics parameters
                 pic_off='warnlight_off.png',                   # picture to display for the disabled light
                 pic_on='warnlight_on.png',                     # picture to display for the enabled light
                 pic_params=None,                               # parameters for the picture command (dict)

                 # sound parameters
                 snd_hit='click2s.wav',                         # correct response to indicator light
                 snd_miss='indicator_miss.wav',                 # missed response to indicator light
                 snd_false='indicator_false.wav',               # false response to indicator light (while off or not focused)
                 no_score_sounds=False,                         # disable regular score sounds in favor of task-specific sounds
                 snd_params=None,                               # parameters for the sound command (dict)

                 # response handling
                 response_key='space',                          # key to press in case of an event
                 timeout=2.5,                                   # response timeout for the user
                 hit_reward=0,                                  # reward if hit
                 miss_penalty=-3,                               # penalty if missed
                 false_penalty=-2,                              # penalty for false positives

                 # ticking/blinking support
                 pic_tick_off = None,                           # optional blinking in off status
                 pic_tick_on = None,                            # optional blinking in on status
                 tick_rate = None,                              # tick rate (duration in non-tick status, duration in tick status)
                 ):

        LatentModule.__init__(self)
        self.scorecounter = scorecounter
        self.stimpresenter = stimpresenter if stimpresenter is not None else self
        self.client_idx = client_idx

        self.focused = focused
        self.event_interval = event_interval

        self.pic_off = pic_off
        self.pic_on = pic_on
        self.pic_params = pic_params

        self.snd_hit = snd_hit
        self.snd_miss = snd_miss
        self.snd_false = snd_false
        self.no_score_sounds = no_score_sounds
        self.snd_params = snd_params

        self.response_key = response_key
        self.timeout = timeout
        self.hit_reward = hit_reward
        self.miss_penalty = miss_penalty
        self.false_penalty = false_penalty
        self.pic_tick_off = pic_tick_off
        self.pic_tick_on = pic_tick_on
        self.tick_rate = tick_rate

    def run(self):
        # prepare the stimuli, etc.
        self.prepare()

        try:
            # create the lightbulb picture
            self.pic = rpyc.enable_async_methods(self.stimpresenter.picture(self.pic_off, max_duration, block=False, **self.pic_params))
            while True:
                # alternate between off and on conditions
                self.off_condition()
                self.on_condition()
        finally:
            # clean up the lightbulb picture
            self.pic.destroy()

    @livecoding
    def prepare(self):
        """ Prepare the task for running. """
        # do a bit of settings post-processing
        if not self.pic_params:
            self.pic_params = {'pos':(0,0),'scale':0.15}
        if not self.snd_params:
            self.snd_params = {'volume':0.3,'direction':0.0}
        if self.pic_tick_on is None:
            self.pic_tick_on = self.pic_on
        if self.pic_tick_off is None:
            self.pic_tick_off = self.pic_off
        self.log_setup_parameters()

        # pre-cache the media files (and get the textures since pic.setTexture doesn't take a file name)
        self.pic_on = rpyc.async(self.stimpresenter.precache_picture)(self.pic_on)
        self.pic_off = rpyc.async(self.stimpresenter.precache_picture)(self.pic_off)
        self.pic_tick_off = rpyc.async(self.stimpresenter.precache_picture)(self.pic_tick_on)
        self.pic_tick_on = rpyc.async(self.stimpresenter.precache_picture)(self.pic_tick_off)
        rpyc.async(self.stimpresenter.precache_sound)(self.snd_hit)
        rpyc.async(self.stimpresenter.precache_sound)(self.snd_miss)
        rpyc.async(self.stimpresenter.precache_sound)(self.snd_false)

        # set up an event watcher (taking care of timeouts and inappropriate responses)
        self.watcher = EventWatcher.EventWatcher(defaultevent=self.response_key,
                                                 handleduration=self.timeout,
                                                 defaulthandler=self.on_false_detection)

    @livecoding
    def off_condition(self):
        """ Put the indicator in off state for a certain time. """
        # show the "off" picture for the inter-event interval
        if self.tick_rate is not None:
            t_end = time.time()+self.event_interval()
            while time.time() < t_end:
                # show the off/tic pic
                self.pic.setTexture(self.pic_tick_off); self.sleep(self.tick_rate[1])
                self.marker('Stimulus/Visual/Indicator Light, Participant/ID/%i, Experiment Control/Task/Indicators/OffBlink' % self.client_idx)
                # show the off pic
                self.pic.setTexture(self.pic_off); self.sleep(self.tick_rate[0])
                self.marker('Stimulus/Visual/Indicator Light, Participant/ID/%i, Experiment Control/Task/Indicators/Off' % self.client_idx)
        else:
            # just show the off pick
            self.pic.setTexture(self.pic_off); self.sleep(self.event_interval())
            self.marker('Stimulus/Visual/Indicator Light, Participant/ID/%i, Experiment Control/Task/Indicators/Off' % self.client_idx)

    @livecoding
    def on_condition(self):
        """ Put the indicator in "on" state for a certain time and wait for the user's response. """
        # start watching for a response
        self.watcher.watch_for(self.on_correct, self.timeout, self.on_missed)
        self.marker('Stimulus/Visual/Indicator Light, Participant/ID/%i, Experiment Control/Task/Indicators/DemandsResponse' % self.client_idx)
        if self.tick_rate is not None:
            t_end = time.time()+self.timeout
            while time.time() < t_end:
                # show the on/tic pic
                self.pic.setTexture(self.pic_tick_on); self.sleep(self.tick_rate[1])
                self.marker('Stimulus/Visual/Indicator Light, Participant/ID/%i, Experiment Control/Task/Indicators/OnBlink' % self.client_idx)
                # show the off pic
                self.pic.setTexture(self.pic_on); self.sleep(self.tick_rate[0])
                self.marker('Stimulus/Visual/Indicator Light, Participant/ID/%i, Experiment Control/Task/Indicators/On' % self.client_idx)
        else:
            # just show the "on" picture
            self.pic.setTexture(self.pic_on); self.sleep(self.timeout)
            self.marker('Stimulus/Visual/Indicator Light, Participant/ID/%i, Experiment Control/Task/Indicators/On' % self.client_idx)
        self.marker('Stimulus/Visual/Indicator Light, Participant/ID/%i, Experiment Control/Task/Indicators/Time Is Up' % self.client_idx)

    @livecoding
    def on_missed(self):
        """ Subject misses to respond in time. """
        if self.focused:
            self.marker('Participant/ID/%i, Experiment Control/Task/Missed Action' % self.client_idx)
            self.scorecounter.score_event(self.miss_penalty,nosound=self.no_score_sounds)
            rpyc.async(self.stimpresenter.sound)(self.snd_miss,**self.snd_params)

    #noinspection PyUnusedLocal
    @livecoding
    def on_false_detection(self,evtype,t):
        """ Subject spuriously presses the response button. """
        self.marker('Participant/ID/%i, Experiment Control/Task/Incorrect Action' % self.client_idx)
        self.scorecounter.score_event(self.false_penalty,nosound=self.no_score_sounds)
        rpyc.async(self.stimpresenter.sound)(self.snd_false,**self.snd_params)

    #noinspection PyUnusedLocal
    @livecoding
    def on_correct(self,evtype,t):
        """ Subject presses the correct response button in time. """
        if self.focused:
            # the user correctly spots the warning event
            self.marker('Participant/ID/%i, Experiment Control/Task/Correct Action' % self.client_idx)
            self.scorecounter.score_event(self.hit_reward,nosound=self.no_score_sounds)
            rpyc.async(self.stimpresenter.sound)(self.snd_hit,**self.snd_params)
        else:
            # the user spotted it, but was not tasked to do so...
            self.marker('Participant/ID/%i, Experiment Control/Task/Incorrect Action' % self.client_idx)
            self.scorecounter.score_event(self.false_penalty,nosound=self.no_score_sounds)
            rpyc.async(self.stimpresenter.sound)(self.snd_false,**self.snd_params)



class CommTask(LatentModule):
    """
    Presents a sequence of distractor statements (audio or textual) from a corpus at semi-random intervals, including
    messages addressed at other callsigns and random chatter. Periodically schedules situations that contain a
    high fraction of statements that are prefixed with the subject's callsign. A fraction of these statements have
    associated yes/no comprehension questions that demand a timely response from the subject.

    Includes optional support for online cognitive state assessment (bringing up an indicator hint).
    """

    def __init__(self,
                 # output environment
                 presenterfunc,                             # stimulus presenter function to use
                 querypresenter,                            # the query presenter
                 targetsign,                                # the subject's assigned callsign (if None, will be randomly selected)
                 client_idx,                                # the subject id, e.g., for markers
                 events,                                    # event names that encode yes, no, and skip (e.g., ['y','n','s'])

                 focused=True,                              # whether this object is in the user's focus

                 # content control
                 command_file='sentences_with_answers.txt', # source file containing a list of actionable commands (sentences and assoc. questions)
                 distractor_file='distractor_sentences.txt',# source file containing a list of distractor sentences
                 callsign_file='callsigns.txt',             # source file containing a list of other call signs
                 numcallsigns=6,                            # subset of callsigns to use

                 # probabilities & timing control
                 lull_time = lambda: random.uniform(20,40),                         # duration of lulls, in seconds (drawn per lull)
                 situation_time = lambda: random.uniform(30,90),                    # duration of developing situations, in seconds (drawn per situation)
                 clearafter = 4,                                                    # clear presenter this many seconds after message display
                 message_interval = lambda: random.uniform(8,15),                   # message interval, in s (drawn per message) (was 12,30)
                 other_callsign_fraction = lambda: random.uniform(0.45,0.55),       # fraction of messages that are for other callsigns (out of all messages presented) (drawn per situation)
                 no_callsign_fraction = lambda: random.uniform(0.05,0.10),          # fraction, out of the messages for "other callsigns", of messages that have no callsign (drawn per situation)
                 time_fraction_until_questions = lambda: random.uniform(0.05,0.15), # the fraction of time into the situation until the first question comes up (drawn per situation)
                                                                                    # in the tutorial mode, this should probably be close to zero
                 questioned_fraction = lambda: random.uniform(0.6,0.8),             # fraction of targeted messages that incur questions
                 post_timeout_silence = lambda: random.uniform(1,3),                # radio silence after a timeout of a question has expired (good idea or not?)

                 # response control
                 response_timeout = 6,                      # response timeout...
                 lock_duration = lambda:random.uniform(7,9),# minimum/maximum duration for which the query presenter is locked
                 loss_incorrect=-2,                         # amount of loss incurred when incorrectly answering
                 gain_correct=2,                            # amount of reward gained when answering correctly
                 loss_skipped=-1,                           # amount of loss incurred when admitting a miss
                 loss_missed=-2,                            # amount of loss incurred when missing the question (and basically the sentence, too)

                 # bci features
                 callback_delay=0.8,                        # query the BCI this many seconds after a "targeted/important" message was displayed 
                 callback_func=None,                        # call this callback function to do it

                 # question counter
                 num_question=0,                            # the current question index from where we continue

                 querydomain='auditory',                    # the domain in which queries should be issued
                 scoredomain='auditory',                    # the domain in which the scores should be counted
                 stimulusdomain = 'auditory'                # the domain in which stimuli appear (this is a HED domain)
                 ):

        LatentModule.__init__(self)
        self.presenterfunc = presenterfunc
        self.querypresenter = querypresenter
        self.client_idx = client_idx
        self.focused = focused
        self.targetsign = targetsign

        # timing parameters
        self.lull_time = lull_time
        self.situation_time = situation_time
        self.message_interval = message_interval
        self.other_callsign_fraction = other_callsign_fraction
        self.no_callsign_fraction = no_callsign_fraction
        self.time_fraction_until_questions = time_fraction_until_questions
        self.questioned_fraction = questioned_fraction
        self.post_timeout_silence = post_timeout_silence

        self.response_timeout = response_timeout
        self.lock_duration = lock_duration
        self.loss_incorrect=loss_incorrect
        self.loss_missed=loss_missed
        self.loss_skipped=loss_skipped
        self.gain_correct=gain_correct

        self.events = events
        self.clearafter = clearafter

        self.callback_delay = callback_delay
        self.callback_func = callback_func

        self.querydomain = querydomain
        self.scoredomain = scoredomain
        self.stimulusdomain = stimulusdomain
        self.num_question = num_question
        self.callsign_file = callsign_file
        self.command_file = command_file
        self.distractor_file = distractor_file
        self.numcallsigns = numcallsigns

    def run(self):
        # load text files
        self.load_callsigns()
        self.load_target_sentences()
        self.load_distractor_sentences()
        # some parameter post-processing
        self.stimulusdomain.capitalize()
        if self.targetsign in self.callsigns:
            self.callsigns.remove(self.targetsign)
        # log all parameters to LSL
        self.log_setup_parameters()

        self.sleep(self.message_interval())
        while True:
            # alternate between lull and action sequences
            self.lull_sequence()
            self.action_sequence()

    # === content loader functions ===

    @livecoding
    def load_callsigns(self):
        self.callsigns = []
        with open(str(ConfigVariableSearchPath('model-path').findFile('media\\'+self.callsign_file)),'r') as f:
            for line in f:
                self.callsigns.append(line.strip())
        self.callsigns = self.callsigns[:self.numcallsigns]

    @livecoding
    def load_target_sentences(self):
        self.sentences = [] # actionable sentences
        self.questions = [] # questions about those sentences
        self.responses = [] # correct answers to the questions
        with open(str(ConfigVariableSearchPath('model-path').findFile('media\\'+self.command_file)),'r') as f:
            for line in f:
                parts = line.split('|')
                try:
                    self.sentences.append(parts[0].strip())
                    self.questions.append(parts[1].strip())
                    resp = parts[2].strip().split(' ')
                    if resp == ['y']:
                        resp = ['yes','no']
                    if resp == ['n']:
                        resp = ['no','yes']
                    self.responses.append(resp)
                except:
                    pass
                    # permute the order of these things
        order = range(len(self.sentences))
        random.shuffle(order)
        self.sentences = [self.sentences[k] for k in order]
        self.questions = [self.questions[k] for k in order]
        self.responses = [self.responses[k] for k in order]
        self.numbering = order

    @livecoding
    def load_distractor_sentences(self):
        # load distractor sentences
        with open(str(ConfigVariableSearchPath('model-path').findFile('media\\'+self.distractor_file)),'r') as f:
            self.distractors = f.readlines()
        random.shuffle(self.distractors)

    # === scheduling functions ===

    @livecoding
    def pause_after_message(self):
        """ Wait for the post-message interval, and optionally query a BCI response at the appropriate time. """
        self.sleep(self.callback_delay)
        if self.callback_func is not None:
            self.callback_func()
        self.sleep(self.message_interval()-self.callback_delay)

    @livecoding
    def lull_sequence(self):
        # begin a lull sequence
        self.marker('Experiment Control/Task/Comms/Lull Begins, Participant/ID/%i' % self.client_idx)
        lull_duration = self.lull_time()
        no_callsign_fraction = self.no_callsign_fraction()
        t_end = time.time() + lull_duration
        while time.time() < t_end:
            # message for another callsign
            if random.random() < no_callsign_fraction:
                # has no callsign
                sentence = random.choice(self.distractors)
                self.presenterfunc(sentence)
                self.marker('Stimulus/%s/Language/Sentence/"%s", Experiment Control/Task/Comms/Distractor/No Callsign, Participant/ID/%i' % (self.stimulusdomain,sentence,self.client_idx))
            else:
                # for another callsign
                sentence = self.substitute(random.choice(self.distractors),random.choice(self.callsigns))
                self.presenterfunc(sentence)
                self.marker('Stimulus/%s/Language/Sentence/"%s", Experiment Control/Task/Comms/Distractor/Other Callsign, Participant/ID/%i' % (self.stimulusdomain,sentence,self.client_idx))
                # wait for the message interval
            self.sleep(self.message_interval())
        self.marker('Experiment Control/Task/Comms/Lull Ends, Participant/ID/%i' % self.client_idx)

    @livecoding
    def action_sequence(self):
        # begin an action sequence
        self.marker('Experiment Control/Task/Comms/Action Sequence Begins, Participant/ID/%i' % self.client_idx)
        situation_time = self.situation_time()
        t_end = time.time() + situation_time
        other_callsign_fraction = self.other_callsign_fraction()
        no_callsign_fraction = self.no_callsign_fraction()
        time_fraction_until_questions = self.time_fraction_until_questions()
        t_beginquestions = time.time() + situation_time * time_fraction_until_questions
        questioned_fraction = self.questioned_fraction()

        while time.time() < t_end:
            if random.random() < other_callsign_fraction:
                # message for another callsign
                if random.random() < no_callsign_fraction:
                    # has no callsign
                    sentence = random.choice(self.distractors)
                    self.presenterfunc(sentence)
                    self.marker('Stimulus/%s/Language/Sentence/"%s", Experiment Control/Task/Comms/Distractor/No Callsign, Participant/ID/%i' % (self.stimulusdomain,sentence,self.client_idx))
                else:
                    # for another callsign
                    sentence = self.substitute(random.choice(self.distractors),random.choice(self.callsigns))
                    self.presenterfunc(sentence)
                    self.marker('Stimulus/%s/Language/Sentence/"%s", Experiment Control/Task/Comms/Distractor/Other Callsign, Participant/ID/%i' % (self.stimulusdomain,sentence,self.client_idx))
                self.sleep(self.message_interval())
            else:
                # message for the current callsign
                if time.time() < t_beginquestions:
                    # no question asked
                    sentence = self.substitute(random.choice(self.distractors),self.targetsign)
                    self.presenterfunc(sentence)
                    self.marker('Stimulus/%s/Language/Sentence/"%s", Experiment Control/Task/Comms/Target/No Question, Participant/ID/%i' % (self.stimulusdomain,sentence,self.client_idx))
                    self.pause_after_message()
                else:
                    if not self.focused or random.random() >= questioned_fraction:
                        # no question asked
                        sentence = self.substitute(random.choice(self.distractors),self.targetsign)
                        self.presenterfunc(sentence)
                        self.marker('Stimulus/%s/Language/Sentence/"%s", Experiment Control/Task/Comms/Target/No Question, Participant/ID/%i' % (self.stimulusdomain,sentence,self.client_idx))
                        self.pause_after_message()
                    else:
                        # first present the sentence; the marker is tagged with the query ID
                        sentence = self.substitute(self.sentences[self.num_question],self.targetsign)
                        self.presenterfunc(sentence)
                        query_id = next(_question_id_generator)
                        self.marker('Stimulus/%s/Language/Sentence/"%s", Experiment Control/Task/Comms/Target/Question/ID/%i, Participant/ID/%i' % (self.stimulusdomain,sentence,query_id,self.client_idx))
                        self.pause_after_message()
                        # generate the query
                        question = StimulusQuestion(
                            client_idx=self.client_idx,
                            category='audiocomm',
                            phrase=self.substitute(self.questions[self.num_question],self.targetsign),
                            correct_answer = self.responses[self.num_question][0],
                            all_answers = self.responses[self.num_question],
                            label = 'question #'+str(self.numbering[self.num_question]),
                            identifier = query_id)
                        # issue it
                        self.querypresenter.submit_question(question,
                            querydomain = self.querydomain,
                            scoredomain = self.scoredomain ,
                            lock_duration = self.lock_duration(),
                            response_timeout = self.response_timeout,
                            onset_delay = 0,
                            loss_incorrect = self.loss_incorrect,
                            gain_correct = self.gain_correct,
                            loss_skipped = self.loss_skipped,
                            loss_missed = self.loss_missed,
                            no_queryprefix = True)
                        self.num_question += 1
                        # wait until we issue the next event...
                        self.sleep(max(self.message_interval(),self.response_timeout+self.post_timeout_silence()))

        self.marker('Experiment Control/Task/Comms/Action Sequence Ends, Participant/ID/%i' % self.client_idx)

    @livecoding
    def substitute(self,command,callsign):
        """Substitute a callsign into a command."""
        if command.find(' *')>0:
            # placeholder not at the beginning
            command.replace('*',callsign.lower())
        elif command.find('*')>0:
            # placeholder at the beginning
            command.replace('*',callsign)
        else:
            # no placeholder, prepend callsign
            command = callsign + '; ' + command
        return command



class SatmapTask(BasicStimuli):    
    """ 
    This class initiates and update of the satellite map content whenever the update() function is called.
    A fraction of the stimuli that have dissappeared last come with associated queries that go through the query presenter.
    """

    def __init__(self,
                 querypresenter,                                # presents queries for satmap events (instance of QueryPresenter)
                 scorecounter,                                  # counts scores and handles reward (instance of ScoreCounter)

                 engine,                                        # instance of the engine that should be used to create the icon resources
                 scenegraph,                                    # scene graph to which the object should be linked
                 util,                                          # utility class (for complex rendering commands and the like)
                 client_idx,                                    # index of the responsible participant

                 local_scenegraph,                              # the local world scene graph (used for item placement criteria)

                 icons_file='icons_with_labels.txt',            # source file containing a list of sounds and associated queries, as well as correct/incorrect responses
                 distractor_fraction = 0.4,                     # fraction of distractor events on the satmap (no question asked) (was 0.7)
                 color_question_fraction = 0.5,                 # fraction of questions that is about object color rather than quadrant
                 changes_per_cycle = lambda:random.choice([0,0,1,1,2]), # a function that returns how many things should change per update cycle (additions and removals count separately)
                 satmap_coverage = (180,180),                   # coverage area of the satellite map (horizontal, vertical, in meters)
                 lock_duration = (3,6),                         # duration for which the query presenter is blocked by satmap-related queries
                 onset_delay = lambda: random.uniform(1,3),     # onset delay of the satmap-related queries
                 response_timeout = 6,                          # response timeout for the queries
                 focused = False,                               # whether this scheduler is currently focused
                 approx_max_items = 1,                          # the approx. number of max. items (if more we'll be adding no more than we remove)
                 angular_ambiguity_zone = 7.5,                  # exclude icons that appear to close to the ambiguity zones (i.e. fall within this many degrees from the zone boundaries)
                 loss_incorrect=-2,                             # amount of loss incurred when incorrectly answering
                 gain_correct=2,                                # amount of reward gained when answering correctly
                 loss_skipped=-1,                               # amount of loss incurred when admitting a miss
                 loss_missed=-2,                                # amount of loss incurred when missing the question (and basically the sentence, too)
                 querydomain = 'visual',                        # domain where the query shall be presented
                 scoredomain='visual',                          # the domain in which the scores should be counted
                 item_colors = None,                            # dict of item names to item colors (4-tuples)
                 item_scale = 8,                                # size of the items, in meters relative to ground
                 constrain_placement=True,                      # whether to constrain the item placement based on city geometry
                 avoid_repetitions=True,                        # whether to avoid repeatedly displaying the same type of item
                 ):
        BasicStimuli.__init__(self)
        self.querypresenter = querypresenter
        self.scorecounter = scorecounter
        self.engine = engine
        self.scenegraph = scenegraph
        self.local_scenegraph = local_scenegraph
        self.icons_file = icons_file
        self.angular_ambiguity_zone =angular_ambiguity_zone
        self.distractor_fraction = distractor_fraction
        self.color_question_fraction = color_question_fraction 
        self.changes_per_cycle = changes_per_cycle
        self.satmap_coverage = satmap_coverage
        self.lock_duration = lock_duration 
        self.onset_delay = onset_delay
        self.response_timeout = response_timeout
        self.focused = focused
        self.approx_max_items = approx_max_items
        self.angular_ambiguity_zone = 5
        self.loss_incorrect=loss_incorrect
        self.loss_missed=loss_missed
        self.loss_skipped=loss_skipped
        self.gain_correct=gain_correct
        self.util = util
        self.item_colors = item_colors
        self.item_scale = item_scale
        self.querydomain = querydomain
        self.scoredomain = scoredomain
        self.client_idx = client_idx
        self.constrain_placement = constrain_placement
        self.avoid_repetitions = avoid_repetitions

        # load the actual media
        self.filenames = []     # icons with associated queries
        self.labels = []        # queries about those icons
        with open(str(ConfigVariableSearchPath('model-path').findFile('media\\'+self.icons_file)),'r') as f:
            for line in f:
                parts = line.split('|')
                try:
                    self.filenames.append(parts[0].strip())
                    self.labels.append(parts[1].strip())
                except:
                    pass

        # permute the order of these things
        order = range(len(self.filenames))
        random.shuffle(order)
        self.filenames = [self.filenames[k] for k in order]
        self.labels = [self.labels[k] for k in order]

        # the list of currently active items
        self.current_icons = []
        self.current_labels = []
        self.current_questions = []

        self.previous_label = ''    # the label that was added last to the map

        if not self.item_colors:
            self.item_colors = {'red':(1,0.25,0.25,1), 'green':(0.25,1,0.25,1), 'blue':(0.25,0.25,1,1), 'yellow':(1,1,0,1)}

        self.log_setup_parameters()

        self.satmap_icon_remover_func = rpyc.async(self.util.conn.modules.framework.ui_elements.WorldspaceGizmos.destroy_worldspace_gizmo)


    @livecoding
    def update(self,centerpos=(0,0,0)):
        """ Update the satellite map. Add or remove items in the current satmap coverage area. """
        # remove old items
        self.remove_items()
        # add new items
        self.add_items(centerpos)

    @livecoding
    def remove_items(self):
        """ Remove a subset of items from the satellite map. """
        # since we don't remove two objects of the same class at once (to prevent ambiguity), we can at most remove
        # as many items as we have unique object types on screen
        num_to_remove = min(len(set(self.current_labels)), self.changes_per_cycle())

        # determine what to remove
        removed_labels = []
        for k in range(num_to_remove):
            while True:
                idx = random.choice(range(len(self.current_icons)))
                # ensure that we don't remove multiple icons of the same type in a single update
                if not (self.current_labels[idx] in removed_labels):
                    removed_labels.append(self.current_labels[idx])

                    # remove it from screen
                    try:
                        self.satmap_icon_remover_func(self.current_icons[idx])
                    except Exception as e:
                        print time.time(), ": Got an async timeout result while trying to delete a satmap item:", e

                    # stimulus offset marker
                    self.marker('Experiment Control/Task/Satellite Map/Remove Icon/{identifier:%i|label:%s}, Participant/ID/%i'% (self.current_questions[idx].identifier, self.current_questions[idx].label, self.client_idx))

                    if self.focused and (random.random() > self.distractor_fraction):
                        # present the associated query
                        self.querypresenter.submit_question(
                            question = self.current_questions[idx],
                            querydomain = self.querydomain,
                            scoredomain = self.scoredomain,
                            lock_duration = self.lock_duration,
                            response_timeout = self.response_timeout,
                            onset_delay = self.onset_delay(),
                            loss_incorrect = self.loss_incorrect,
                            gain_correct = self.gain_correct,
                            loss_skipped = self.loss_skipped,
                            loss_missed = self.loss_missed)

                    # discard associated question
                    self.current_questions[idx].discard_marker()

                    del self.current_icons[idx]
                    del self.current_labels[idx]
                    del self.current_questions[idx]
                    break

    @livecoding
    def add_items(self,centerpos):
        """ Add some new items to the satellite map. """
        num_to_add = min(self.changes_per_cycle(), self.approx_max_items - len(self.current_icons))

        # add them
        for k in range(num_to_add):
            pos = []
            angle = 0
            radius = 0
            while True:
                # chose random position
                if self.constrain_placement:
                    pos = generate_positions(
                        scenegraph=self.local_scenegraph,
                        objectnames=['Pavement','Concrete','Street'],
                        within_box=((centerpos[0]-self.satmap_coverage[0]/2,centerpos[0]+self.satmap_coverage[0]/2),(centerpos[1]-self.satmap_coverage[1]/2,centerpos[1]+self.satmap_coverage[1]/2),(-10000,10000)),snap_to_navmesh=False)[0]
                else:
                    pos = (random.uniform(centerpos[0]-self.satmap_coverage[0]/2,centerpos[0]+self.satmap_coverage[0]/2),
                           random.uniform(centerpos[1]-self.satmap_coverage[1]/2,centerpos[1]+self.satmap_coverage[1]/2), centerpos[2])

                # label the compass direction into which the position falls
                diff = (pos[0]-centerpos[0],pos[1]-centerpos[1])
                screendiff = (-diff[1],diff[0])
                angle = math.atan2(screendiff[0],screendiff[1]) * 180.0 / 3.14
                radius = math.hypot(screendiff[0],screendiff[1])

                # ensure that the direction is not ambiguous
                ambiguous = False
                for boundary_angle in [-45,45,-135,135]:
                    if abs(angle - boundary_angle) < self.angular_ambiguity_zone:
                        ambiguous = True
                if ambiguous:
                    continue

                if angle < -135 or angle > 135:
                    direction = 'south'
                elif angle < -45:
                    direction = 'west'
                elif angle < 45:
                    direction = 'north'
                elif angle <= 135:
                    direction = 'east'
                break

            # chose a random shape
            while True:
                # but make sure that its label differs from the previously added label
                shapeidx = random.choice(range(len(self.filenames)))
                filename = self.filenames[shapeidx]
                label = self.labels[shapeidx]
                if not (self.avoid_repetitions and label == self.previous_label):
                    break

            # chose a random color
            color = random.choice(self.item_colors.keys())

            # pre-determine the question to be asked (if we ask it) and the correct answer.
            if random.random() < self.color_question_fraction:
                # ask a color question
                question = StimulusQuestion(category="color",phrase="What was the color of the last " + label + '?',
                    correct_answer=color,all_answers=self.item_colors.keys(),label=label,client_idx=self.client_idx)
            else:
                # ask a direction question
                question = StimulusQuestion(category="compass",phrase="What was the direction of the last " + label + '?',
                    correct_answer=direction,all_answers=['north','south','east','west'],label=label,client_idx=self.client_idx)

            # generate the picture instance
            icon = rpyc.async(self.util.conn.modules.framework.ui_elements.WorldspaceGizmos.create_worldspace_gizmo)(
                image=filename, scale=self.item_scale, position=pos,color=self.item_colors[color], parent=self.scenegraph, camera_mask=(3,4))
            # issue stimulus presentation marker
            self.marker('Stimulus/Visual/Shape, Experiment Control/Task/Satellite Map/Add Icon/{identifier:%i|label:%s|color:%s|direction:%s|x:%f|y:%f|phi:%f|r:%f}, Participant/ID/%i'% (question.identifier, question.label, color, direction, pos[0], pos[1], angle, radius, self.client_idx))

            # append to the list
            self.current_icons.append(icon)
            self.current_labels.append(label)
            self.current_questions.append(question)

            self.previous_label = label


class SoundTask(LatentModule):
    """
    A task in which sounds are played back from various directions. A fraction of sounds come with associated questions
    about the direction of the sound.
    """

    def __init__(self,
                 # output environment
                 querypresenter,                                # the query presenter
                 stimpresenter,                                 # instance of BasicStimuli to present the actual sounds
                 client_idx,                                    # ID of the responsible participant

                 # timing control
                 sound_interval = lambda: random.uniform(10,18),# interval between sound events
                 lock_duration = (7,9),                         # duration for which the query presenter is blocked by sound-queries
                 onset_delay = lambda: random.uniform(2,4),     # onset delay of the sound-related queries
                 response_timeout = 7,                          # response timeout for the queries
                 focused = False,                               # whether this scheduler is currently focused

                 # scoring
                 loss_incorrect=-2,                             # amount of loss incurred when incorrectly answering
                 gain_correct=2,                                # amount of reward gained when answering correctly
                 loss_skipped=-1,                               # amount of loss incurred when admitting a miss
                 loss_missed=-2,                                # amount of loss incurred when missing the question (and basically the sentence, too)

                 # misc
                 sound_directions=None,                         # mapping from sound direction labels to angles (relative to listener)
                 sounds_file='sounds_with_labels.txt',          # source file containing a list of sounds and associated queries, as well as correct/incorrect responses
                 distractor_fraction = 0.5,                     # fraction of distractor events on the satmap (no question asked)
                 sound_volume = 0.5,                            # volume modifier of the sounds
                 querydomain='auditory',                        # domain where the query shall be presented
                 scoredomain='auditory',                        # the domain in which the scores should be counted
                 ):

        LatentModule.__init__(self)
        self.querypresenter = querypresenter
        self.stimpresenter = stimpresenter if stimpresenter is not None else self
        self.sounds_file = sounds_file
        self.distractor_fraction = distractor_fraction 
        self.sound_interval = sound_interval
        self.lock_duration = lock_duration
        self.onset_delay = onset_delay
        self.response_timeout = response_timeout
        self.focused = focused
        self.loss_incorrect = loss_incorrect
        self.gain_correct = gain_correct
        self.loss_skipped = loss_skipped
        self.loss_missed = loss_missed
        self.sound_directions = sound_directions
        self.sound_volume = sound_volume
        self.client_idx = client_idx
        self.sounds_file = sounds_file
        self.querydomain = querydomain
        self.scoredomain = scoredomain

        self.filenames = []     # icons with associated label
        self.labels = []        # labels about those icons

    @livecoding
    def load_media(self):
        # load the stimulus material
        with open(str(ConfigVariableSearchPath('model-path').findFile('media\\'+self.sounds_file)),'r') as f:
            for line in f:
                parts = line.split('|')
                try:
                    self.filenames.append(parts[0].strip())
                    self.labels.append(parts[1].strip())
                except:
                    pass

        # permute the order of these things
        order = range(len(self.filenames))
        random.shuffle(order)
        self.filenames = [self.filenames[k] for k in order]
        self.labels = [self.labels[k] for k in order]

    def run(self):
        # load things
        self.load_media()
        if not self.sound_directions:
            self.sound_directions = {'front':0, 'left':-0.707, 'right':0.707, 'back':1.414}
        self.log_setup_parameters()

        while True:
            # wait until the next sound comes up
            self.sleep(self.sound_interval())

            # determine properties
            direction = random.sample(self.sound_directions.keys(),1)[0]
            angle = self.sound_directions[direction]

            # chose a random file
            soundidx = random.choice(range(len(self.filenames)))
            filename = self.filenames[soundidx]
            label = self.labels[soundidx]

            # pre-compute the associated question
            question = StimulusQuestion(category="sound_direction", phrase="What was the direction of the last " + label + ' sound?',
                correct_answer=direction, all_answers=self.sound_directions.keys(),label=label, client_idx = self.client_idx)

            # emit the sound and onset marker
            rpyc.async(self.stimpresenter.sound)(filename,direction=angle,volume=self.sound_volume,block=False)
            if self.client_idx==0:
                print "Now playing " + label + " on " + direction + "..."
            self.marker('Stimulus/Auditory/File/"%s", Stimulus/Auditory/Direction/%s, Experiment Control/Task/Sound Events/{identifier:%i|label:%s}, Participant/ID/%i' % (filename, direction.capitalize(), question.identifier, question.label, self.client_idx))

            if self.focused and (random.random() > self.distractor_fraction):
                # schedule the query
                self.querypresenter.submit_question(
                    question = question,
                    querydomain = self.querydomain,
                    scoredomain = self.scoredomain,
                    lock_duration = self.lock_duration,
                    response_timeout = self.response_timeout,
                    onset_delay = self.onset_delay(),
                    loss_incorrect = self.loss_incorrect,
                    gain_correct = self.gain_correct,
                    loss_skipped = self.loss_skipped,
                    loss_missed = self.loss_missed)



_entity_id_generator = itertools.count(1)   # a generator to assign experiment-wide unique id's to entities on the sidewalk

class ProbedObjectsTask(LatentModule):
    """
    A task that plays out in the world space and is therefore shared between both subjects. A collection of objects are
    pseudo-randomly scattered on the sidewalks of the city. When a subject drives by one of these objects, he/she may
    get an associated question about the object after it has gone out of view (currently the direction left/right at which
    the object was when the subject drove by it. A small fraction of object categories comes with no associated question
    but needs to be reported within a certain response time (e.g., suspicious objects).
    """

    class TrackedEntity:
        """
        Information about a tracked entity in the city environment; this is to determine when a question should be issued.
        """

        def __init__(self,
                     pos,               # position in the world
                     color,             # color word
                     label,             # object label (e.g. "chair")
                     removers,          # list of functions to remove the node when done
                     ):
            self.pos = pos
            self.color = color
            self.label = label
            self.removers = removers
            self.identifier = next(_entity_id_generator)
            # the following properties are tracked per subject
            self.is_candidate = [False]*len(self.removers)                    # whether this entity is a candidate for later questioning if it goes out of sight at some point             
            self.has_been_clearly_visible_since = [None]*len(self.removers)   # has consistently been in plain sight since this point in time 
            self.has_generated_question = [False]*len(self.removers)          # whether this entity has generated a question already 
            self.has_been_sufficiently_invisible_since = [None]*len(self.removers) # has consistently been sufficiently far out of sight since this point in time
            self.has_been_invisible_since = [None]*len(self.removers)         # has consistently been strictly invisible since this point in time
            self.excluded_from_questions = [False]*len(self.removers)         # whether this entity is excluded from generating questions (e.g. due to potential ambiguity or since it was a distractor)
            self.last_visible_side = [None]*len(self.removers)                # this is 'left' or 'right' depending on where the entity was last visible (in the subject's fov) 
            self.is_visible = [False]*len(self.removers)                       # whether this entity is currently visible 

    @livecoding
    def __init__(self,
                 querypresenters,                           # the query presenters for the two subjects
                 report_scorecounters,                      # score counters for the reporting task (one per subject)

                 # relevant game state 
                 agents,                                    # reference to the agents for which the objects & questions should be generated
                 scenegraph,                                # the master scene graph for geometry calculations
                 navmesh,                                   # a navmesh on the scene graph to enforce reachability constraints
                 physics,                                   # a bullet physics world to enforce line-of-sight constraints
                 display_scenegraphs,                       # the scene graphs to which the objects should be added (the 0th graph is the local graph
                 display_funcs,                             # the functions to display the instances (signature-compatible with create_worldspace_instance),
                                                            # a list of pairs (first one is the constructor, second one the destructor)
                 display_engines,                           # engine instances to load the models...

                 active_agents = None,                      # list of indices of agents for whom to update items and generate questions (default: range(len(agents)))
                                                            # can be updated at runtime by modifying self.active_agents

                 # source content
                 item_file = 'objects_with_labels.txt',     # the list of map objects to scatter on sidewalks
                 item_scale = 2.54/100.0,                   # fallback scaling for all items (to be overridden by per-iitem file content)
                 item_height = 0.0,                         # fallback height for all items (to be overridden by per-iitem file content)
                 item_colors = None,                        # color map for color questions (dict from label to RGBA 4-tuble)

                 # adding and pruning entities
                 placement_geometry = 'Pavement',           # this is the target geometry for placing objects
                 add_within_fov = 50,                       # add items within the given field of view (but behind buildings, i.e., around corners)
                 num_potentially_visible = 15,              # the initial number of simultaneously potentially visible objects to maintain (may be varied over time)
                 max_visible = 10,                          # don't add more objects if there are currently this many objects in view
                 add_radius_max = 75,                       # add new potentially visible objects within this radius, in meters (note: should also use cone segment constraint!)
                 add_radius_min = 15,                       # add new potentially visible objects outside this radius, in meters
                 entity_height = 1,                         # height of the entities above ground, for more accurate visibility tests
                 max_retries_per_cycle = 15,                # this determines how much time per frame may be spent trying to sample positions to be added
                 prune_radius = 100,                        # prune old objects when they pass out of this radius (and are invisible)
                 prune_viewcone = 90,                        # objects outside this viewcone can be pruned (if they are far enough away)

                 # promotion of objects to candidates for questions                 
                 candidate_radius = 20,                      # objects can only become candidate for questions if they get within this radius
                 candidate_viewcone = 55,                    # objects can only become candidate for questions if they get within this ("inner") view cone
                 candidate_visible_duration = 0.7,           # objects can only become candidates if they stay in view for this long
                 vischeck_max_cutoff = 150,                  # maximum cutoff for the visibility test, as an optimization (should be larger than candidate_radius)

                 # issuance of questions
                 ask_outside_viewcone = 60,                  # object must be outside a view cone this large to be considered for questioning
                 ask_after = 2,                              # object must have been outside the viewcone for this many seconds to generate a question (and stayed in this status)
                 ask_relative_movement = 1,                  # object must be moving away from agent at at least this relative speed (i.e., merely turning away does not trigger a question)    
                 drop_candidate_after = 6,                   # drop an object from potential candidacy if it has stayed outside the inner viewcone for this many seconds
                                                             # (note: no question will be asked if there is at least one more candidate of the same object category)
                 # question details
                 distractor_fraction = 0.4,                 # probability of a candidate event triggering no question (= a distractor)
                 color_question_fraction = 0.0,              # fraction of questions that is about object color rather than side
                 lock_duration = (5,6),                      # duration for which the query presenter is blocked by the queries
                 onset_delay = lambda: random.uniform(0,2),  # onset delay of the queries
                 response_timeout = 5,                       # response timeout for the queries

                 # reporting details
                 reportable_objects = ('Sand bags',),        # subset of objects that should be reported directly
                 reportable_timeout = 5,                     # timeout for reporting reportable objects
                 reportable_score_multiplier = 2,            # score multiplier for gain/loss/etc in case of reportable items
                 reportable_fraction = 0.05,                 # fraction of reportable items among all items

                 # scoring
                 loss_incorrect=-2,                          # amount of loss incurred when incorrectly answering
                 gain_correct=2,                             # amount of reward gained when answering correctly
                 loss_skipped=-1,                            # amount of loss incurred when admitting a miss
                 loss_missed=-2,                             # amount of loss incurred when missing the question (and basically the sentence, too)

                 # misc
                 querydomain='visual',                       # domain where the query shall be presented
                 scoredomain='visual',                       # the domain in which the scores should be counted
                 ):

        LatentModule.__init__(self)
        self.focused = [False,False]                         # replicate initial focused state for each agent
        self.querypresenters = querypresenters
        self.report_scorecounters = report_scorecounters
        self.agents = agents
        self.display_scenegraphs = display_scenegraphs
        self.display_engines = display_engines
        self.display_funcs = display_funcs
        self.scenegraph = scenegraph 
        self.navmesh = navmesh
        self.physics = physics 

        self.item_file = item_file
        self.item_colors = item_colors
        self.item_scale = item_scale
        self.item_height = item_height

        self.placement_geometry = placement_geometry
        self.add_within_fov = add_within_fov
        self.num_potentially_visible = num_potentially_visible
        self.max_visible = max_visible
        self.add_radius_min = add_radius_min
        self.add_radius_max = add_radius_max
        self.prune_radius = prune_radius
        self.prune_viewcone = prune_viewcone
        self.entity_height = entity_height
        self.vischeck_max_cutoff = vischeck_max_cutoff
        self.max_retries_per_cycle = max_retries_per_cycle

        self.candidate_radius = candidate_radius
        self.candidate_viewcone = candidate_viewcone
        self.candidate_visible_duration = candidate_visible_duration

        self.ask_outside_viewcone = ask_outside_viewcone
        self.ask_after = ask_after
        self.ask_relative_movement = ask_relative_movement
        self.drop_candidate_after = drop_candidate_after

        self.distractor_fraction = distractor_fraction
        self.color_question_fraction = color_question_fraction
        self.lock_duration = lock_duration
        self.onset_delay = onset_delay
        self.response_timeout = response_timeout

        self.reportable_objects = reportable_objects
        self.reportable_score_multiplier = reportable_score_multiplier
        self.reportable_timeout = reportable_timeout
        self.reportable_fraction = reportable_fraction

        self.loss_incorrect = loss_incorrect
        self.gain_correct = gain_correct
        self.loss_skipped = loss_skipped
        self.loss_missed = loss_missed
        self.querydomain = querydomain
        self.scoredomain = scoredomain

        # init runtime variables
        self.labels = []                   # labels for the placeable 3d models
        self.entities = []                 # the current set of entities on the map
        self.active_agents = range(len(self.agents)) if active_agents is None else active_agents # the set of agents for whom to generate items and questions

    @livecoding
    def load_media(self):
        """ Load media files from disk. """
        self.models = []
        for i in range(len(self.display_engines)):
            self.models.append(dict())
        with open(str(ConfigVariableSearchPath('model-path').findFile('media\\'+self.item_file)),'r') as f:
            for line in f:
                parts = line.split('|')
                filename = parts[0].strip()
                label = parts[1].strip()
                scale = float(parts[2].strip()) if len(parts) > 2 else self.item_scale
                height = float(parts[3].strip()) if len(parts) > 3 else self.item_height
                self.labels.append(label)
                for i in range(len(self.display_engines)):
                    # load it
                    self.models[i][label] = rpyc.enable_async_methods(self.display_engines[i].base.loader.loadModel(filename))
                    self.models[i][label].setScale(scale)
                    self.models[i][label].setPos(0,0,height)

    @livecoding
    def run(self):
        self.load_media()
        if not self.item_colors:
            self.item_colors = {'red':(1,0.25,0.25,1), 'green':(0.25,1,0.25,1), 'blue':(0.25,0.25,1,1), 'yellow':(1,1,0,1)}
        self.log_setup_parameters()

        while True:
            self.sleep(0.1)
            if len(self.active_agents) == 0:
                continue

            # get current positions of the agents
            agent_positions = []
            for i in range(len(self.agents)):
                agent_positions.append(self.agents[i].getPos(self.scenegraph))
            # also get their view cones
            agent_viewdirs = []
            for i in range(len(self.agents)):
                tmpdir = self.agents[i].getParent().getMat(self.scenegraph).getRow(1)
                tmpdir.normalize()
                agent_viewdirs.append(Vec3(tmpdir.getX(),tmpdir.getY(),tmpdir.getZ()))

            # maintain the desired number of potentially visible items (by adding new ones if necessary)
            self.add_items(agent_positions,agent_viewdirs)
            # update the status of the items (visible, etc) and schedule queries if applicable
            self.update_items(agent_positions,agent_viewdirs)
            # prune old / out-of-view items
            self.prune_items(agent_positions,agent_viewdirs)

    @livecoding
    def add_items(self,agent_positions, agent_viewdirs):
        """ Depending on the new positions/orientations of the agents consider adding new items. """

        # consider adding new objects (note: if we re-activate them later we should only count those that have not been pruned)
        while len(self.entities) < self.num_potentially_visible:
            # determine a good spawn position
            pos = generate_positions(scenegraph=self.scenegraph, navmesh=self.navmesh, physics=self.physics,
                objectnames=self.placement_geometry,
                invisible_from=agent_positions,                                                     # none of the players should see it pop up (whether active or not)
                nearby_to=[agent_positions[k] for k in self.active_agents],                         # is nearby to any of the active agents
                nearby_radius=self.add_radius_max,
                nearby_param = 'any',
                within_cone=[[agent_positions[k],agent_viewdirs[k]] for k in self.active_agents],   # is within viewcone of any of the active agents
                within_cone_angle = self.add_within_fov,
                within_cone_param = 'any',
                away_radius=self.add_radius_min,
                snap_to_navmesh=False,
                max_retries=self.max_retries_per_cycle
            )
            if len(pos) == 0:
                break # in some cases the conditions can be unsatisfiable; in this case we don't add
            pos = pos[0]

            # pick a random object label
            if random.random() < self.reportable_fraction:
                # from the reportable set
                label = random.choice(self.reportable_objects)
            else:
                # from the non-reportable set
                label = random.choice(list(set(self.labels).difference(set(self.reportable_objects))))
            # pick a random color
            color = random.choice(self.item_colors.keys())

            # add it to the display scene graphs (keeping track of them in scene_instances)
            # added to both agent's worldspace since the world should be consistent for both
            removers = []
            for i in range(len(self.display_scenegraphs)):
                g = self.display_scenegraphs[i]
                m = self.models[i][label]
                inst = rpyc.async(self.display_funcs[i][0])(model=m,
                    position=(pos.getX(),pos.getY(),pos.getZ()),hpr=(random.random()*360,0,0),
                    color=self.item_colors[color],parent=g)
                removers.append((self.display_funcs[i][1],inst))

            new_entity = ProbedObjectsTask.TrackedEntity(pos=pos,color=color,label=label,removers=removers)
            # generate marker for logging
            self.marker('Experiment Control/Task/Sidewalk Items/Add/{identifier:%i|label:%s|color:%s|x:%f|y:%f|z:%f}' % (new_entity.identifier,label,color,pos[0],pos[1],pos[2]))
            # add to tracking list
            self.entities.append(new_entity)
            print "len(entities) =",len(self.entities)

    @livecoding
    def update_items(self,agent_positions, agent_viewdirs):
        """ Update the status of the items (visible, etc) and schedule queries if applicable. """

        # status updates and logic for the agents
        for a in range(len(self.agents)):
            apos = agent_positions[a]
            adir = agent_viewdirs[a]

            for e in range(len(self.entities)):
                ent = self.entities[e]

                # calc current distance, visibility, etc.
                distance = (ent.pos - apos).length()
                strictly_visible = line_of_sight(physics=self.physics,
                    src_pos=apos,
                    dst_pos=Point3(ent.pos.getX(),ent.pos.getY(),ent.pos.getZ()+self.entity_height),
                    src_dir=adir,
                    src_maxsight=self.vischeck_max_cutoff,
                    src_fov=self.candidate_viewcone,
                    dst_margin=2) is not None
                sufficiently_invisible = line_of_sight(physics=self.physics,
                    src_pos=apos,
                    dst_pos=Point3(ent.pos.getX(),ent.pos.getY(),ent.pos.getZ()+self.entity_height),
                    src_dir=adir,
                    src_maxsight=self.vischeck_max_cutoff,
                    src_fov=self.ask_outside_viewcone,
                    dst_margin=2) is None

                if ent.is_visible[a] != strictly_visible:
                    ent.is_visible[a] = strictly_visible
                    self.marker('Experiment Control/Task/Sidewalk Items/Becomes %s/{identifier:%i}, Participants/ID/%i' % ('Visible' if strictly_visible else 'Invisible',ent.identifier,a))

                # promote objects to candidacy for possible later questioning if they have been in plain sight for long enough
                if distance < self.candidate_radius and strictly_visible:
                    if ent.has_been_clearly_visible_since[a] is None:
                        self.marker('Stimulus/Visual/3D Object/%s, Experiment Control/Task/Sidewalk Items/Becomes Closely Visible/{identifier:%i}, Participants/ID/%i' % (ent.label,ent.identifier,a))
                        ent.has_been_clearly_visible_since[a] = time.time()
                    if time.time() - ent.has_been_clearly_visible_since[a] > self.candidate_visible_duration and not ent.has_generated_question[a] and not ent.is_candidate[a]:
                        self.marker('Experiment Control/Task/Sidewalk Items/Becomes Question Candidate/{identifier:%i}, Participants/ID/%i' % (ent.identifier,a))
                        ent.is_candidate[a] = True
                    # calculate on what side the stimulus was last sighted
                    diff = Vec3(ent.pos - apos)
                    if diff.normalize():
                        ent.last_visible_side[a] = 'left' if agent_viewdirs[a].signedAngleDeg(diff,Vec3(0,0,1)) > 0 else 'right'
                    else:
                        ent.last_visible_side[a] = 'undetermined' # (should rarely if ever happen)
                else:
                    ent.has_been_clearly_visible_since[a] = None

                # demoting entities from candidacy after some timeout (and also from the potential conflict set)
                if not strictly_visible:
                    if ent.has_been_invisible_since[a] is None:
                        ent.has_been_invisible_since[a] = time.time()
                    if time.time() - ent.has_been_invisible_since[a] > self.drop_candidate_after and ent.is_candidate[a]:
                        self.marker('Experiment Control/Task/Sidewalk Items/Dropped As Question Candidate/{identifier:%i}, Participants/ID/%i' % (ent.identifier,a))
                        ent.is_candidate[a] = False
                else:
                    ent.has_been_invisible_since[a] = None

                # consider questions for scheduling (for the candidate set)
                if self.focused[a] and ent.is_candidate[a] and not ent.has_generated_question[a] and not ent.excluded_from_questions[a]:
                    if a not in self.active_agents:
                        # if the agent is not active we exclude this item from questions
                        # note that all other properties are still tracked intentionally -- since we don't want questions to pop up out of the blue after an agent becomesa active again
                        ent.excluded_from_questions[a] = True
                        continue

                    color = ent.color
                    label = ent.label
                    direction = ent.last_visible_side[a]

                    if label in self.reportable_objects:
                        self.marker('Experiment Control/Task/Sidewalk Items/Expecting Subject Report/{identifier:%i|label:%s}, Participants/ID/%i' % (ent.identifier,label,a))
                        # this is a special reportable object: we expect a response from the subject
                        if self.waitfor('cl' + str(a) + '-report',duration=self.reportable_timeout):
                            # subject reponded in time
                            print str(time.time()) + ": subject responded in time to suspicious object"
                            self.marker('Experiment Control/Task/Action/Correct, Experiment Control/Task/Sidewalk Items/Reported Object/{identifier:%i}, Participants/ID/%i' % (ent.identifier,a))
                            self.report_scorecounters[a].score_event(self.gain_correct*self.reportable_score_multiplier,nosound=False)
                        else:
                            # failed to respond
                            print str(time.time()) + ": subject failed to respond to suspicious object"
                            self.marker('Experiment Control/Task/Action/Missed, Experiment Control/Task/Sidewalk Items/Failed To Report Object/{identifier:%i}, Participants/ID/%i' % (ent.identifier,a))
                            self.report_scorecounters[a].score_event(self.loss_missed*self.reportable_score_multiplier)
                        ent.has_generated_question[a] = True

                    elif sufficiently_invisible:
                        # regular explicitly probed object
                        if ent.has_been_sufficiently_invisible_since[a] is None:
                            ent.has_been_sufficiently_invisible_since[a] = time.time()

                        if time.time() - ent.has_been_sufficiently_invisible_since[a] > self.ask_after:

                            # check if the question can be scheduled unambiguously
                            collision = False
                            for k in set(range(len(self.entities))) - set([e]):
                                other = self.entities[k]
                                if other.label == ent.label and other.is_candidate[a] and not other.has_generated_question[a] and not other.is_visible[a]:
                                    collision = True
                            if collision:
                                ent.excluded_from_questions[a] = True
                                self.marker('Experiment Control/Task/Sidewalk Items/Dropped Due To Ambiguity/{identifier:%i|label%s}, Participants/ID/%i' % (ent.identifier,ent.label,a))
                                continue

                            if random.random() > self.distractor_fraction:
                                # schedule the actual question!
                                if random.random() < self.color_question_fraction:
                                    # ask a color question
                                    question = StimulusQuestion(
                                        category="color", phrase="What was the color of the last " + label + '?',
                                        correct_answer=color, all_answers=self.item_colors.keys(), label=label, client_idx=a)
                                else:
                                    # ask a direction question
                                    question = StimulusQuestion(
                                        category="viewside", phrase="On what side was the last " + label + '?',
                                        correct_answer=direction, all_answers=['left','right'],label=label, client_idx=a)

                                print "*** " + str(time.time()) + " issueing question for " + color + " " + label + " on " + direction + " side of the camera view"
                                self.marker('Experiment Control/Task/Sidewalk Items/Generating Question/{item_identifier:%i|question_identifier:%i}, Participants/ID/%i' % (ent.identifier,question.identifier,a))

                                # actually present the query
                                self.querypresenters[a].submit_question(
                                    question = question,
                                    querydomain = self.querydomain,
                                    scoredomain = self.scoredomain,
                                    lock_duration = self.lock_duration,
                                    response_timeout = self.response_timeout,
                                    onset_delay = self.onset_delay(),
                                    loss_incorrect = self.loss_incorrect,
                                    gain_correct = self.gain_correct,
                                    loss_skipped = self.loss_skipped,
                                    loss_missed = self.loss_missed)

                                ent.has_generated_question[a] = True
                            else:
                                # take this event as a distractor
                                print "*** " + str(time.time()) + " generated distractor event for " + color + " " + label + " on " + direction + " side of the camera view"
                                self.marker('Experiment Control/Task/Sidewalk Items/Take As Distractor/{item_identifier:%i|label:%s}, Participants/ID/%i' % (ent.identifier,ent.label,a))
                                ent.excluded_from_questions[a] = True

                    else:
                        ent.has_been_sufficiently_invisible_since[a] = None

    @livecoding
    def prune_items(self,agent_positions,agent_viewdirs):
        """ Prune old / out-of-view items. """
        for e in reversed(range(len(self.entities))):
            # check if it's out of range and outside the field of view for both agents...
            in_range = False
            for a in self.active_agents:
                pos = self.entities[e].pos
                direction = pos - agent_positions[a]
                if direction.length() < self.prune_radius or direction.normalize() and abs(agent_viewdirs[a].angleDeg(direction)) < self.prune_viewcone/2:
                    in_range = True
            if not in_range:
                # delete it
                print "Trying to delete entity..."
                for remover in self.entities[e].removers:
                    rpyc.async(remover[0])(remover[1])
                self.marker('Experiment Control/Task/Sidewalk Items/Remove/{identifier:%i|label:%s|color:%s|x:%f|y:%f|z:%f}' % (self.entities[e].identifier,self.entities[e].label,self.entities[e].color,pos[0],pos[1],pos[2]))
                del self.entities[e]

    def set_focused(self,idx,tf):
        """ Set the focused state of this task for a given agent/client. """
        self.focused[idx] = tf


# ==========================
# === WORLD-SPACE AGENTS ===
# ==========================

_agent_id_generator = itertools.count(1)   # a generator to assign experiment-wide unique id's to agents (both wanderers, invaders, etc.)

class WanderingAgent(BasicStimuli):
    """
    A type of agent that is wandering around from random checkpoint to random checkpoint
    (initially spawned relative to some position).
    Note: a few positions are in the detour coordinate system; we generally append _detour to their names here for clarity.
    """

    def __init__(self,
                 # world data bases for control
                 crowd,                     # the navigation crowd that holds the agents
                 physics,                   # a bullet physics world for line-of-sight checks
                 surfacegraph,              # a scene graph that controls the surface placement of checkpoints & spawn locations...
                 valid_surfaces=('Street','Concrete','Pavement'), # names of objects whose surfaces may serve as spawn and checkpoint locations

                 # display control
                 scene_graphs=(),           # scene graphs to which to add the renderable models
                 engines=(),                # engine instances maintaianing these scene graphs
                 models=(),                 # the models that should be added to those scene graphs

                 # control of the initial spawn location 
                 spawn_pos=None,            # center point of an area in which to spawn (or None if no such area)
                 spawn_radius_min=25,       # minimum distance from the center point (if any)
                 spawn_radius_max=100,      # maximum distance from the center point (if any)
                 line_of_sight=None,        # if set to False, the agent will initially be out of line-of-sight from the spawn location

                 # control of wandering behavior
                 wander=True,               # whether to actively wander around randomly
                 maxspeed = 3,              # maximum movement speed
                 replan_min=50,             # minimum distance of next target from current position
                 replan_max=200,            # maximum distance of next target from current position
                 snap_radius=50,            # tolerance for movement destinations that are not strictly on the navmesh

                 # jump animation (when reported)
                 jump_duration = 0.3,       # duration of the jump, in seconds
                 jump_height = 0.5,         # jump height, in meters

                 box_constraint = None,     # box constraints for agent movement ((minx,maxx),(miny,maxy),(minz,maxz))
                 ):
        BasicStimuli.__init__(self)
        self.crowd = crowd
        self.physics = physics
        self.surfacegraph = surfacegraph
        self.valid_surfaces = valid_surfaces  
        self.mesh = crowd.nav
        self.maxspeed = maxspeed
        self.wander = wander
        self.replan_min = replan_min
        self.replan_max = replan_max
        self.snap_radius = snap_radius
        self.box_constraint = box_constraint
        self.jump_duration = jump_duration
        self.jump_height = jump_height

        # if there is a spawn_pos, generate a position that is a certain distance from that given location,
        # and with no line-of-sight to it (otherwise random); generally restrict to valid surfaces
        pos = generate_positions(scenegraph=self.surfacegraph, navmesh=self.mesh, physics=self.physics,
            objectnames = self.valid_surfaces,
            invisible_from = None if line_of_sight is None else (None if spawn_pos is None else spawn_pos),
            reachable_from = None if spawn_pos is None else spawn_pos,
            away_from = None if spawn_pos is None else spawn_pos,
            nearby_to = None if spawn_pos is None else spawn_pos,
            nearby_radius = spawn_radius_max,
            away_radius = spawn_radius_min,
            max_retries=100000,
            within_box = self.box_constraint)[0]

        # initialize runtime variables
        self.pos = pos                                      # current position in panda3d coordinates
        self.vel = Point3(0,0,0)                            # current velocity in panda3d coordinates
        self.identifier = next(_agent_id_generator)         # unique agent identifier (constant)
        self.crowdidx = self.crowd.add_agent(loc=self.pos,maxspeed=self.maxspeed)   # id in the nav data structure (constant)

        # add to scene graphs
        self.instances = []
        self.pos_functions = []
        self.lookat_functions = []
        for i in range(len(scene_graphs)):
            g = scene_graphs[i]
            m = models[i]
            inst = rpyc.enable_async_methods(g.attachNewNode("WanderingAgent"))
            inst.setPos(self.pos.getX(),self.pos.getY(),self.pos.getZ())
            # also hide the agent from all the satmap cameras
            for c in [0,1]:
                inst.hide(engines[i].pandac.BitMask32.bit(c))
            self.instances.append(inst)
            m.instanceTo(inst)
            self.pos_functions.append(inst.setPos)
            self.lookat_functions.append(inst.lookAt)
        self.marker('Experiment Control/Task/Agents/Wanderers/Add/{identifier:%i|wander:%s|x:%f|y:%f|z:%f}' % (self.identifier,str(self.wander),self.pos[0],self.pos[1],self.pos[2]))

        # init a few more trackable properties per subject (the mission code will track these if necessary)
        self.is_directly_visible = [False,False]
        self.is_directly_invisible = [False,False]
        self.directly_visible_since = [0,0]
        self.directly_invisible_since = [0,0]
        self.was_directly_visible_for = [0,0]
        self.is_potentially_visible = [False,False]
        self.is_potentially_invisible = [False,False]
        self.potentially_visible_since = [0,0]
        self.potentially_invisible_since = [0,0]
        self.was_potentially_visible_for = [0,0]
        self.last_report_time = [0,0]
        self.last_spotting_time = [0,0]
        self.last_retreat_time = 0                          # last time when this agent started to retreat (needed to time the jump animation)

    def __del__(self):
        self.crowd.remove_agent(self.crowdidx)
        for inst in self.instances:
            inst.removeNode()
        self.marker('Experiment Control/Task/Agents/Wanderers/Remove/{identifier:%i|wander:%s}' % (self.identifier,str(self.wander)))

    @livecoding
    def move_to_location(self,pos):
        """ Instruct the agent to move to a particular location. """
        target_detour = self.mesh.nearest_point(pos=pos, radius=self.snap_radius)
        self.crowd.request_move_target(self.crowdidx, target_detour)
        self.marker('Experiment Control/Task/Agents/Wanderers/Move To/{identifier:%i|wander:%s|x:%f|y:%f|z:%f}' % (self.identifier,str(self.wander),pos[0],pos[1],pos[2]))

    @livecoding
    def on_reported(self):
        self.last_retreat_time = time.time()

    @livecoding
    def update(self):
        """ Update the current position and consider to replan. """
        status = self.crowd.agent_status(self.crowdidx)
        # update camera position and velocity
        self.pos = status.npos
        self.vel = status.vel
        if self.vel.length() <= 0.001 and self.wander:
            # propose a new target location if we reached the destination or got stuck
            target_detour = self._propose_next_destination(self.pos)
            self.crowd.request_move_target(self.crowdidx, target_detour)
            target = navigation.detour2panda(target_detour[1])
            self.marker('Experiment Control/Task/Agents/Wanderers/Wander To/{identifier:%i|wander:%s|x:%f|y:%f|z:%f}' % (self.identifier,str(self.wander),target[0],target[1],target[2]))
        else:
            # get the jump offset (simple parabola)
            jump_time = time.time() - self.last_retreat_time
            jump_offset = 0.0 if jump_time > self.jump_duration else (1 - (jump_time/self.jump_duration - 0.5)**2 * 4) * self.jump_height
            # update position in all scene graphs
            for i in range(len(self.pos_functions)):
                self.pos_functions[i](self.pos.getX(),self.pos.getY(),self.pos.getZ() + jump_offset)
                if self.vel.length() > 0:
                    self.lookat_functions[i](self.pos.getX()+self.vel.getX(),self.pos.getY()+self.vel.getY(),self.pos.getZ()+jump_offset+self.vel.getZ())

    @livecoding
    def _propose_next_destination(self,curpos):
        """ Find a new possible wander destination relative to the given (current) position. Used to implement the wandering. """
        newpos_detour = generate_positions(scenegraph=self.surfacegraph, navmesh=self.mesh, physics=self.physics,
            objectnames = self.valid_surfaces,
            away_from = curpos,
            nearby_to = curpos,
            nearby_radius = self.replan_max,
            away_radius = self.replan_min,
            output_coord_sys='detour',
            within_box = self.box_constraint)[0]
        return newpos_detour



class InvadingAgent(BasicStimuli):
    """
    A type of agent that attempts to invade (approach) a particular location. Once it has reached a safe distance it
    rests (what is considered safe enough is depending on the current "mood" parameter) for a while until it moves
    even closer. The agent can be threatened away by player actions (controlled by the main script), which put the
    agent in a mode where it attempts to retreat behind a building at a farther distance, until it eventually comes out
    again.
    Note: a few positions are in the detour coordinate system; we generally append _detour to their names here for clarity.
    """

    def __init__(self,
                 crowd,                     # navigation crowd data structure
                 bulletworld,               # physics system (for line-of-sight checks)

                 # display control
                 scene_graphs,              # scene graphs to which to add the renderable models
                 engines,                   # engines that are maintaining these scene graphs
                 models,                    # the models that should be added to those scene graphs

                 # behavioral control
                 hotspot,                   # position that will be invaded (the "hotspot")
                 initial_mood=0,            # initial mood setting: -10 = very shy, 0 = neutral, 10 = very aggressive
                 state_duration=(10,20),    # duration for which the agent remains in waiting or hidden states
                 min_distance=10,           # the closest that the agent will ever get to the hotspot
                 max_distance = 300,        # the farthest that the agent will ever get from the hotspot
                 maxspeed = 3,              # maximum movement speed
                 enter_building_probability = 0.0, # probability of entering a building after having completed a retreat
                 snap_radius=50,            # tolerance for movement destinations that are not strictly on the navmesh

                 # jump animation (when warned off)
                 jump_duration = 0.3,       # duration of the jump, in seconds
                 jump_height = 0.5,         # jump height, in meters

                 # spawn control
                 spawn_pos=None,            # center position where to spawn the agent
                 jitter=300,                # maximum radius around the center position
                 ):
        BasicStimuli.__init__(self)

        self.crowd = crowd
        self.mesh = crowd.nav
        self.bulletworld = bulletworld
        self.jitter = jitter
        self.maxspeed = maxspeed
        self.state_duration = state_duration
        self.min_distance = min_distance
        self.max_distance = max_distance
        self.hotspot = hotspot
        self.mood = initial_mood
        self.enter_building_probability = enter_building_probability
        self.snap_radius = snap_radius
        self.jump_duration = jump_duration
        self.jump_height = jump_height

        # pick random spawn location around the spawn_pos
        pos_detour = self._propose_nearby_loc(spawn_pos)

        # initialize runtime variables
        self.pos = navigation.detour2panda(pos_detour[1])   # current position in Panda3d coordinates
        self.vel = Point3(0,0,0)                            # current velocity in Panda3d coordinates
        self.mode = ""                                      # current behavioral state; can be "approaching", "waiting", "retreating", "towardsbuilding", "hiding"
        self.identifier = next(_agent_id_generator)         # unique identifier (constant)
        self.crowdidx = self.crowd.add_agent(loc=pos_detour,maxspeed=self.maxspeed) # id in the navigation data structure (constant)
        self.last_retreat_time = 0                          # last time when this agent started to retreat (needed to time the jump animation)

        # add to scene graphs
        self.instances = []
        self.pos_functions = []
        self.lookat_functions = []
        for i in range(len(scene_graphs)):
            g = scene_graphs[i]
            m = models[i]
            inst = rpyc.enable_async_methods(g.attachNewNode("InvadingAgent"))
            inst.setPos(self.pos.getX(),self.pos.getY(),self.pos.getZ())
            # also hide the agent from the satmap cameras (using the appropriate masks)
            for c in [0,1]:
                inst.hide(engines[i].pandac.BitMask32.bit(c))
            self.instances.append(inst)
            m.instanceTo(inst)
            self.pos_functions.append(inst.setPos)
            self.lookat_functions.append(inst.lookAt)
            self.instances.append(inst)

        # emit creation marker
        self.marker('Experiment Control/Task/Agents/Invaders/Add/{identifier:%i|x:%f|y:%f|z:%f}' % (self.identifier,self.pos[0],self.pos[1],self.pos[2]))

        # initially enter waiting mode...
        self.enter_wait()

    def __del__(self):
        self.crowd.remove_agent(self.crowdidx)
        for inst in self.instances:
            inst.removeNode()
        self.marker('Experiment Control/Task/Agents/Invaders/Remove/{identifier:%i}' % self.identifier)

    @livecoding
    def enter_wait(self):
        self.mode = "waiting"
        self.wait_ends_at = time.time() + random.uniform(self.state_duration[0],self.state_duration[1])
        self.marker('Experiment Control/Task/Agents/Invaders/Wait/{identifier:%i|mood:%f|x:%f|y:%f|z:%f}' % (self.identifier,self.mood,self.pos[0],self.pos[1],self.pos[2]))
        print 'An agent chose to wait.'

    @livecoding
    def enter_approach_hotspot(self):
        # propose a new target position whose proximity to the hotspot matches the current mood level        
        self.mode = "approaching"
        self.mood = min(self.mood + 3,10)
        target_detour = self._propose_loc_around_hotspot(maintain_hotspot_los=True)
        self.crowd.request_move_target(self.crowdidx, target_detour)
        print 'An agent is approaching!'
        target = navigation.detour2panda(target_detour[1])
        self.marker('Experiment Control/Task/Agents/Invaders/Approach/{identifier:%i|mood:%f|x:%f|y:%f|z:%f|tx:%f|ty:%f|tz:%f}' % (self.identifier,self.mood,self.pos[0],self.pos[1],self.pos[2],target[0],target[1],target[2]))

    @livecoding
    def enter_retreat(self,spotter_pos):
        self.mode = "retreating"
        self.mood = max(self.mood - 9,-10)
        target_detour = self._propose_loc_around_hotspot(spotter_pos=spotter_pos, maintain_hotspot_los=False)
        self.crowd.request_move_target(self.crowdidx, target_detour)
        self.last_retreat_time = time.time()
        print  'An agent is retreating!'
        target = navigation.detour2panda(target_detour[1])
        self.marker('Experiment Control/Task/Agents/Invaders/Retreat/{identifier:%i|mood:%f|x:%f|y:%f|z:%f|tx:%f|ty:%f|tz:%f}' % (self.identifier,self.mood,self.pos[0],self.pos[1],self.pos[2],target[0],target[1],target[2]))

    @livecoding
    def enter_towards_building(self):
        self.mode = "towardsbuilding"
        target_detour = self.mesh.nearest_edge_point(self.mesh.nearest_point(pos=self.pos, radius=self.snap_radius))
        self.crowd.request_move_target(self.crowdidx, target_detour)
        print  'An agent is moving towards a building.'
        target = navigation.detour2panda(target_detour[1])
        self.marker('Experiment Control/Task/Agents/Invaders/Towards Building/{identifier:%i|mood:%f|x:%f|y:%f|z:%f|tx:%f|ty:%f|tz:%f}' % (self.identifier,self.mood,self.pos[0],self.pos[1],self.pos[2],target[0],target[1],target[2]))

    @livecoding
    def enter_hide(self):
        self.mode = "hiding"
        for inst in self.instances:
            inst.hide()
        self.wait_ends_at = time.time() + random.uniform(self.state_duration[0],self.state_duration[1])
        print  'An agent has entered a building!'
        self.marker('Experiment Control/Task/Agents/Invaders/Hide/{identifier:%i|mood:%f|x:%f|y:%f|z:%f}' % (self.identifier,self.mood,self.pos[0],self.pos[1],self.pos[2]))

    @livecoding
    def update(self):
        status = self.crowd.agent_status(self.crowdidx)
        # update camera position and velocity
        self.pos = status.npos
        self.vel = status.vel
        if self.mode == "waiting":
            if time.time() > self.wait_ends_at:
                self.enter_approach_hotspot()
        elif self.mode == "hiding":
            if time.time() > self.wait_ends_at:
                print 'An agent came out of a building.'
                # come out of the building again...
                for inst in self.instances:
                    inst.show()
                self.marker('Experiment Control/Task/Agents/Invaders/Unhide/{identifier:%i|mood:%f|x:%f|y:%f|z:%f}' % (self.identifier,self.mood,self.pos[0],self.pos[1],self.pos[2]))
                self.enter_approach_hotspot()
        else:
            if self.vel.length() <= 0.001:
                # reached the goal...
                if self.mode == "retreating": 
                    if random.random() < self.enter_building_probability:
                        self.enter_towards_building()
                    else:
                        self.enter_wait()
                elif self.mode == "approaching":
                    self.enter_wait()
                elif self.mode == "towardsbuilding":
                    self.enter_hide()
            else:
                # get the jump offset (simple parabola)
                jump_time = time.time() - self.last_retreat_time
                jump_offset = 0.0 if jump_time > self.jump_duration else (1 - (jump_time/self.jump_duration - 0.5)**2 * 4) * self.jump_height
                # update position in all scene graphs
                for i in range(len(self.pos_functions)):
                    self.pos_functions[i](self.pos.getX(),self.pos.getY(),self.pos.getZ() + jump_offset)
                    self.lookat_functions[i](self.pos.getX()+self.vel.getX(),self.pos.getY()+self.vel.getY(),self.pos.getZ()+jump_offset+self.vel.getZ())

    @livecoding
    def _propose_nearby_loc(self,pos):
        """
        Propose a position in the vicinity of the given position.
        Input: in panda3d coordinates, output: in detour coordinates.
        """
        pos = (pos[0] + random.uniform(-self.jitter,self.jitter), pos[1] + random.uniform(-self.jitter,self.jitter), pos[2])
        return self.mesh.nearest_point(pos=pos, radius=self.snap_radius)

    @livecoding
    def _propose_loc_around_hotspot(self, maintain_hotspot_los=None, spotter_pos=None):
        """
        Find a location relative to the hotspot that has line-of-sight and whose distance corresponds to the mood of the agent.
        The output is in detour coordinates
        """
        if maintain_hotspot_los is None:
            # if the mood is > 0 the entity attempts to maintain line-of-sight with the hotspot
            maintain_hotspot_los = self.mood > 0
        distance = self.min_distance + (self.max_distance-self.min_distance)*(self.mood+10)/20
        tmp = self.pos - self.hotspot
        old_angle = math.atan2(tmp[1], tmp[0])   # this is the old angle at which the person is currently standing
        distance_tolerance = 0
        angular_tolerance = 3.1415/4
        while True:
            # we try to find a position that is approximately in the same direction from the hotspot but matches the current mood,
            # in terms of distance and in whether they maintain line-of-sight with the hotspot or not
            # and if we cannot satisfy it, we relax the criterion incrementally until we are successful
            distance_tolerance = max(self.min_distance,min(self.max_distance,distance_tolerance + 2.5))
            angular_tolerance += 0.05
            # pick a random angle in a particular cone that is growing with each retry
            random_ang = old_angle + random.uniform(-angular_tolerance,angular_tolerance)
            random_dist = distance + random.uniform(-distance_tolerance,distance_tolerance)
            pos = (self.hotspot[0] + math.cos(random_ang)*random_dist, self.hotspot[1] + math.sin(random_ang)*random_dist, self.hotspot[2])
            # find nearest point on mesh
            meshloc_detour = self.mesh.nearest_point(pos=pos, radius=self.snap_radius)
            # determine if the line-of-sight matches what we want
            pnt = navigation.detour2panda(meshloc_detour[1])
            has_los = line_of_sight(self.bulletworld,pnt,self.hotspot) is not None
            if has_los == maintain_hotspot_los:
                if spotter_pos is not None:
                    # also make sure that the point is not in the LOS of the object which spotted this agent (if any)
                    if line_of_sight(self.bulletworld,spotter_pos,pnt) is not None:
                        continue
                    # found a valid position
                return meshloc_detour


_gizmo_id_generator = itertools.count(1)   # a generator to assign experiment-wide unique id's to agents (both wanderers, invaders, etc.)

class SmartGizmo(BasicStimuli):
    """
    Represents a movable gizmo that renders/updates itself on multiple scene graphs (usually viewports of the subjects and the experimenter),
    and which can optionally be masked from pre-defined camera types (satellite map, 3d viewport) and endowed with different rendering effects.
    Supports position clamping at some rectangle (and maybe later at 3d viewport boundaries).
    """
    def __init__(self,
                 # rendering output
                 display_scenegraphs,    # the scene graphs to which the objects should be added
                 display_funcs,          # the functions to display/delete the instances as list of pairs (first one is the constructor, second one the destructor), signature-compatible with (create_worldspace_gizmo,destroy_worldspace_gizmo)
                 display_engines,        # engine instances to load the models...
                 client_indices,         # the client indices corresponding to the respective list entries in display_*** (referred to in the clip-box / clamp-box updates)
                 # display properties
                 pos=(0,0,0),            # initial position of the gizmo
                 hpr=(0,0,0),            # initial heading/pitch/roll angles of the gizmo
                 scale = 2,              # scale of the icon
                 image = 'icons/star.png',# the icon to use (can also be a list of strings to assign a different icon per scene graph)
                 opacity=0.95,           # opacity of the icon
                 oncamera=True,          # whether the gizmo is visible on the 3d camera (can also be a list of booleans, e.g. [True,False], to assign a different setting per scene graph)
                 onsatmap=True,          # whether the gizmo is visible on the satellite map (can also be a list of booleans, e.g. [True,False], to assign a different setting per scene graph)
                 onexperimenter=True,    # whether the gizmo is visible on the experimenter's screen
                 throughwalls=True,      # whether the gizmo is visible through walls of buildings (can also be a list of booleans, e.g. [True,False], to assign a different setting per scene graph)
                 billboard=True,         # whether to enable a billboard effect (always points to the respective camera)
                 gizmo_name='',          # name of the gizmo for marker purposes (no markers if empty)
                 sat_scale=None,         # optionally the scale on the satellite map (overrides global scale)
                 cam_scale=None          # optionally the scale on the cam viewport (overrides global scale)
                 ):
        BasicStimuli.__init__(self)

        self.display_scenegraphs = display_scenegraphs
        self.display_funcs = display_funcs
        self.display_engines = display_engines
        self.client_indices = client_indices

        if type(image) is not list:
            image = [image]*len(self.display_scenegraphs)
        if type(oncamera) is not list:
            oncamera = [oncamera]*len(self.display_scenegraphs)
        if type(onsatmap) is not list:
            onsatmap = [onsatmap]*len(self.display_scenegraphs)
        if type(throughwalls) is not list:
            throughwalls = [throughwalls]*len(self.display_scenegraphs)
        self.image = image
        self.scale = scale
        self.opacity = opacity
        self.oncamera = oncamera
        self.onsatmap = onsatmap
        self.onexperimenter = onexperimenter
        self.throughwalls = throughwalls
        self.gizmo_name = gizmo_name
        self.identifier = next(_gizmo_id_generator)         # unique identifier (constant)
        self.sat_scale = sat_scale if sat_scale else scale
        self.cam_scale = cam_scale if cam_scale else scale

        # run-time variables
        self.cam_gizmos = []        # holds a list of scene nodes visible on the camera, one per display scene graph
        self.sat_gizmos = []        # holds a list of scene nodes visible on the satmap, one per display scene graph
        self.pos = pos
        self.hpr = hpr
        self.clip_boxes = [None]*len(self.display_scenegraphs)
        self.clamp_boxes = [None]*len(self.display_scenegraphs)

        # generate it on every output
        for k in range(len(self.display_scenegraphs)):
            # add a version that's only visible on 3d cameras (but never on satmaps)
            self.cam_gizmos.append(rpyc.async(self.display_funcs[k][0])(
                position = self.pos,
                hpr = self.hpr,
                scale=self.cam_scale,
                image=self.image[k],
                parent=self.display_scenegraphs[k],
                engine=self.display_engines[k],
                color=(1,1,1,self.opacity),
                camera_mask = ((3,4) if not self.oncamera[k] else ()) + (0,1) + ((2,) if not self.onexperimenter else ()),
                billboard=billboard,
                throughwalls=self.throughwalls[k]))
            # add a version that's at best visible on satmaps (but never on 3d cameras)
            self.sat_gizmos.append(rpyc.async(self.display_funcs[k][0])(
                position = self.pos,
                hpr = self.hpr,
                scale=self.sat_scale,
                image=self.image[k],
                parent=self.display_scenegraphs[k],
                engine=self.display_engines[k],
                color=(1,1,1,self.opacity),
                camera_mask = ((0,1) if not self.onsatmap[k] else ()) + (2,3,4),
                billboard=billboard,
                throughwalls=True))
        if self.gizmo_name:
            self.marker('Experiment Control/Task/%s/Create/{identifier:%i|x:%f|y:%f|z:%f}' % (self.gizmo_name,self.identifier,self.pos[0],self.pos[1],self.pos[2]))

    @livecoding
    def update_satmap_clamp_box(self,cl_idx,box):
        """ Update the satmap clamp box (if any) that shall constrain the position of this checkpoint for a given client index. """
        if cl_idx in self.client_indices:
            self.clamp_boxes[self.client_indices.index(cl_idx)] = box
            self.update()

    @livecoding
    def update_satmap_clip_box(self,cl_idx,box):
        """ Update the satmap clip box (if any) outside of which the item is going to be invisible. """
        if cl_idx in self.client_indices:
            self.clip_boxes[self.client_indices.index(cl_idx)] = box
            self.update()

    @livecoding
    def move_to(self,pos,hpr=None):
        """ Move a checkpoint to a new location. """
        self.pos = pos
        if hpr:
            self.hpr = hpr
        self.update()
        if self.gizmo_name:
            self.marker('Experiment Control/Task/%s/Move/{identifier:%i|x:%f|y:%f|z:%f}' % (self.gizmo_name,self.identifier,self.pos[0],self.pos[1],self.pos[2]))

    @livecoding
    def update(self):
        """ Update the location of the checkpoint. """
        for g in self.cam_gizmos:
            rpyc.async(g.setPos)(self.pos[0],self.pos[1],self.pos[2])
        for k in range(len(self.sat_gizmos)):
            # implement clipping
            if self.clip_boxes[k]:
                if self.pos[0] < self.clip_boxes[k][0] or self.pos[0] > self.clip_boxes[k][1] or self.pos[1] < self.clip_boxes[k][2] or self.pos[1] > self.clip_boxes[k][3] or self.pos[2] < self.clip_boxes[k][4] or self.pos[2] > self.clip_boxes[k][5]:
                    rpyc.async(self.sat_gizmos[k].setColor)(1,1,1,0)
                else:
                    rpyc.async(self.sat_gizmos[k].setColor)(1,1,1,self.opacity)
            # implement clamping
            if self.clamp_boxes[k]:
                clamppos = (clamp(self.pos[0],self.clamp_boxes[k][0],self.clamp_boxes[k][1]),
                            clamp(self.pos[1],self.clamp_boxes[k][2],self.clamp_boxes[k][3]),
                            clamp(self.pos[2],self.clamp_boxes[k][4],self.clamp_boxes[k][5]))
            else:
                clamppos = self.pos
            rpyc.async(self.sat_gizmos[k].setPosHpr)(clamppos[0],clamppos[1],clamppos[2],self.hpr[0],self.hpr[1],self.hpr[2])

    @livecoding
    def destroy(self):
        """ Remove a checkpoint from the world. """
        for g in self.cam_gizmos:
            g.destroy()
        for g in self.sat_gizmos:
            g.destroy()
        self.cam_gizmos = []
        self.sat_gizmos = []
        if self.gizmo_name:
            self.marker('Experiment Control/Task/%s/Remove/{identifier:%i}' % (self.gizmo_name,self.identifier))


# =========================================
# === SCENE LOADING/HANDLING BASE CLASS ===
# =========================================

class SceneBase(LatentModule):
    """
    Wrapper around a (potentially remote) intance of the Panda3d engine (self._engine, field of the LatentModule) that contains
    basic mechanisms for scene graph operations (like loading the world and accessing certain special objects).
    Used as base class by both the game server (e.g., for experimenter's view and collision detection) as well as the
    game clients (for rendering).
    """

    def __init__(self):
        LatentModule.__init__(self)

        # navmesh parameters
        self.max_total_agents = 20                      # upper capacity of the navigation data structures

        # terrain placement parameters         
        self.terrainsize = 10000                        # size of the terrain map, in meters (edge length)
        self.terrainheight = 400.0                      # height of the terrain, in meters (black to white is rescaled to this range)
        self.terrain_offset = -32.35                    # vertical offset of the terrain, in meters
        self.terrain_rot = 0                            # rotation of the terrain, in degrees
        self.terrain_rescale = (0.74,0.74,1.0)          # rescaling factor of the terrain (for whatever reason...)

        # city placement parameters
        self.cityscale = 1.0                            # unit conversion factor for the city model

        # agent placement parameters
        self.hostile_filename = 'media/hostile_drone-anim.bam'# file name of the hostile agent model  ('media/towdroid_rev.bam')
        self.hostile_scale = 2.54/100.0                 # unit conversion into meters (here from inches)
        self.hostile_height = 1.5 #0                    # offset of the hostile model from the ground, in meters

        self.friendly_filename = 'media/r5_rev.bam'     # file name of the friendly agent model (note: these are the voice-controllable robots)
        self.friendly_scale = 2.54/100.0                # unit conversion into meters (here from inches)
        self.friendly_height = -0.3                     # offset of the friendly model from the ground, in meters

        # geomipmapping control parameters
        self.geomip_blocksize = 128
        self.geomip_near_distance = 3000                # distance below which the terrain is maintain maximum resolution (in meters)
        self.geomip_far_distance = 20000                # distance beyond which the terrain is at minimum resolution (in meters)                

        # sky parameters
        self.sky_color = (0.6, 0.5, 1)                  # RGB color of the sky

        # static world nodes
        self.world_root = None                          # root node of the world scene graph
        self.city = None                                # city model
        self.terrain = None                             # terrain node
        self.skybox = None                              # textured skybox model
        self.navmesh = None                             # the navigation mesh
        self.navcrowd = None                            # the navigation "crowd" (containing all navigating agents)

    @livecoding
    def create_static_world(self,modelname=None,terrainname=None,skyname=None,remove_checkpoints=False):
        """ Load the static game world. """
        self.write("Loading world; please wait...",duration=0.5,block=False)
        self.world_root = self._engine.pandac.NodePath('world_root')

        # load the navmesh
        searchpath = ConfigVariableSearchPath('model-path')
        meshfile = str(searchpath.findFile('media/' + modelname + '.dat'))
        if not meshfile:
            raise Exception("Could not find navmesh for model named " + modelname)
        self.navmesh = navigation.NavMesh(navmesh=meshfile)
        self.navcrowd = navigation.NavCrowd(self.navmesh,maxagents=self.max_total_agents)

        # load the model for the hostile agents
        self.hostile_model = rpyc.enable_async_methods(self._engine.base.loader.loadModel(self.hostile_filename))
        self.hostile_model.setScale(self.hostile_scale) 
        self.hostile_model.setPos(0,0,self.hostile_height)

        # load the model for the friendly agents
        self.friendly_model = rpyc.enable_async_methods(self._engine.base.loader.loadModel(self.friendly_filename))
        self.friendly_model.setScale(self.friendly_scale) 
        self.friendly_model.setPos(0,0,self.friendly_height)         

        # load the city model
        if modelname is not None:
            print "Loading model",modelname,"...",
            self.city = rpyc.enable_async_methods(self._engine.base.loader.loadModel('media/' + modelname + '.bam'))
            self.city.setScale(self.cityscale)
            self.city.setName("CityNode")
            self.city.reparentTo(self.world_root)
            print "done."

        # load the terrain
        if terrainname is not None:
            print "Loading terrain",terrainname,"...",
            # set up terrain properties
            self.terrain = rpyc.enable_async_methods(self._engine.pandac.GeoMipTerrain("terrain"))
            self.terrain_heightmap = str(searchpath.findFile('media/' + terrainname + '_height.png'))
            self.terrain.setHeightfield(self.terrain_heightmap)
            self.terrain_colormap = str(searchpath.findFile('media/' + terrainname + '_color.png'))
            self.terrain.setColorMap(self.terrain_colormap)
            self.terrain.setBlockSize(self.geomip_blocksize)
            self.terrain.setNear(self.geomip_near_distance)
            self.terrain.setFar(self.geomip_far_distance)
            # link into scene
            self.terrain_node = rpyc.enable_async_methods(self._engine.pandac.NodePath('terrain_rot'))
            self.terrain_node.reparentTo(self.world_root)
            self.terrain_node.setScale(self.terrain_rescale[0],self.terrain_rescale[1],self.terrain_rescale[2])
            self.terrain_root = rpyc.enable_async_methods(self.terrain.getRoot())
            self.terrain_root.reparentTo(self.terrain_node)
            self.terrain_root.setPos(-self.terrainsize/2 + 0.5,-self.terrainsize/2 + 0.5,self.terrain_offset)
            self.terrain_root.setScale(self.terrainsize/1025.0,self.terrainsize/1025.0,self.terrainheight)
            self.terrain_root.setBin("background", 1)
            self.terrain_root.setDepthOffset(-1)
            self.terrain.generate()
            print "done."

        # load the skybox
        if skyname is not None:
            print "Loading skybox",terrainname,"...",
            self.skybox = rpyc.enable_async_methods(self._engine.base.loader.loadModel('media/' + skyname + '.egg'))
            self.skybox.setBin("background",0)
            self.skybox.setDepthWrite(False)
            self.skybox.setCompass()
            self.skybox.reparentTo(self.world_root)
            print "done."

        if remove_checkpoints:
            print "Post-processing models...",
            for node in self.city.findAllMatches('**/Checkpoint*'):
                rpyc.async(node.removeNode)()
            print "done."

        # remove all StartPos instances except for one
        startpos_nodes = self.city.findAllMatches('**/StartPos*')
        if len(startpos_nodes) > 1:
            retain_idx = random.choice(range(len(startpos_nodes)))
            for k in range(len(startpos_nodes)):
                if not k == retain_idx:
                    rpyc.async(startpos_nodes[k].removeNode)()
                for c in startpos_nodes[retain_idx].getChildren():
                    rpyc.async(c.wrtReparentTo)(self.city())

        # get the position of the waypoint at the starting location
        try:
            waypoint = self.city.find("**/Waypoint*-lib*")
            self.waypoint_pos = waypoint.getPos(self.city)
            rpyc.async(waypoint.removeNode)()
        except:
            print "This environment contains no startpos waypoint."
            self.waypoint_pos = None

    @livecoding
    def destroy_static_world(self):
        """Unload the static game world."""
        if self.city is not None:
            self._engine.base.loader.unloadModel(self.city)
        if self.terrain is not None:
            self._engine.base.loader.unloadModel(self.terrain)
        if self.skybox is not None:
            self._engine.base.loader.unloadModel(self.skybox)

    @livecoding
    def create_viewport(self,rect,cam):
        """Create a new viewport into the game world that is associated with a camera."""
        viewport = rpyc.enable_async_methods(self._engine.base.win.makeDisplayRegion(rect[0],rect[1],rect[3],rect[2]))
        viewport.setClearColor(self._engine.pandac.VBase4(self.sky_color[0], self.sky_color[1], self.sky_color[2], 1))
        viewport.setClearColorActive(True)
        viewport.setClearDepthActive(True)
        viewport.setCamera(cam)
        return viewport

    def find_agent(self,name):
        """Create an agent instance (actually look it up from what's contained in the scene anyway)."""
        tmp = self.city.find("**/" + name + "*")
        return tmp


# ==============================
# === MAIN PER-SUBJECT LOGIC ===
# ==============================

class ClientGame(SceneBase):
    """
    This class implements the per-subject ("per-client") logic, which is mostly related to the UI and the
    UI-related subtasks. In a two-subject experiment there are two instances of this class around.
    While it runs on the experimenter's computer it maintains an active connection to the remote engine instance
    (which serves as audiovisual canvas with its own scene graph that is populated and updated as necessary); most of
    the drawing commands therefore go directly to the remote scene graph or engine instance.
    """

    def __init__(self,
                 master,         # the master module (Main)
                 num,            # sequence number of this client (0 or 1)
                 initial_score=0 # initial score of the client
                 ):
        """ Init the client game session."""
        SceneBase.__init__(self)
        self.master = master                                # reference to the local game master
        self.hostname = ''                                  # hostname to connect to (assigned later)
        self.port = 0                                       # port to connect to (assigned later)
        self.num = num                                      # client index (index in the master's client table, 0-based)
        self.id = ''                                        # callsign of the subject (assigned later)
        self.tag = 'cl'+str(num)                            # tag of this client, for example in event messages
        self.initial_score = initial_score                  # initial score of the client

        # client GUI settings
        self.viewport_corner_pos = grid(2,(1,1),(2,5),'topleft')  # position of the 3d viewport upper left corner (aspect2d coordinates)
        self.agent_viewport_rect = rect(grid(2,(1,1),(2,5),'topleft',sys='window'),grid(2,(1,1),(3,5),'bottomright',sys='window')) # viewport rectangle that displays the own agent's camera (in normalized window coordinates)
        self.icon_clamp_distance = 2                        # when clamping satellite map icons at the border, this is the distance from the border in meters on ground

        # placement of instruction text boxes
        self.viewport_instructions_pos = grid(2,(1,1),(4,5),'topleft') # position of the instruction message box (upper left corner)
        self.viewport_instructions_width = 18               # width of the instruction message box (in characters)
        self.viewport_instructions_height = 4               # width of the instruction message box (in characters)

        self.satmap_instructions_pos = grid(3,(1,1),(4,5),'topleft')  # position of the satmap instruction message box (upper left corner)
        self.satmap_instructions_width = 18                 # width of the instruction message box (in characters)
        self.satmap_instructions_height = 3                 # width of the instruction message box (in characters)

        self.comm_message_pos = grid(1,(1,1),(3,5),'topleft') # position of the text comm chatter scroll box (aspect2d coordinates)
        self.comm_message_width = 36                        # width of the text comm chatter scroll box (in characters)
        self.comm_message_height = 13                       # height of the text comm chatter scroll box (in characters)

        self.missiontext_instructions_pos = grid(2,(1,1),(5,5),'topleft',mov=(0,0.05)) # position of the instruction message box (upper left corner)
        self.missiontext_instructions_width = 18               # width of the instruction message box (in characters)
        self.missiontext_instructions_height = 4               # width of the instruction message box (in characters)

        # stress indicator
        self.stress_pos = grid(1,(2,5),(4,5))               # position of the stress indicator (aspect2d coordinates)
        self.stress_size = 0.16                             # size of the stress indicator

        # warning light
        self.warn_pos = grid(1,(4,5),(4,5))                 # position of the red warning light (aspect2d coordinates)
        self.warn_size = 0.16                               # size of the red warning light

        # sound eff gizmos
        self.sound_gizmo_pos = grid(1,(2,5),(1,5))          # position of the sound effects icon (this is a symbol representing that sound effects channel)
        self.sound_gizmo_size = 0.15                        # size of the audiocomm icon
        self.sound_gizmo_pic = str(ConfigVariableSearchPath('model-path').findFile('icons\\sound_generic.png')) # picture of the sound effects icon
        # vocal comm gizmo
        self.audiocomm_gizmo_pos = grid(1,(4,5),(1,5))      # position of the audiocomm icon (this is a symbol representing that audio channel)
        self.audiocomm_gizmo_size = 0.15                    # size of the audiocomm icon
        self.audiocomm_gizmo_pic = str(ConfigVariableSearchPath('model-path').findFile('icons\\comm.png')) # picture of the audiocomm icon
        self.gizmo_corner_offset = 0.13

        # attention indicator frames
        self.text_attention_frame = rect(grid(1,(1,1),(3,5),'topleft',exp=(0.02,0.03)),grid(1,(1,1),(3,5),'bottomright',exp=(0.02,0.03)))
        self.viewport_attention_frame = rect(grid(2,(1,1),(2,5),'topleft',exp=(0.02,0.015)),grid(2,(1,1),(4,5),'bottomright',exp=(0.02,0.015)))
        self.satmap_attention_frame = rect(grid(3,(1,1),(2,5),'topleft',exp=(0.02,0.015)),grid(3,(1,1),(4,5),'bottomright',exp=(0.02,0.015)))
        self.vocal_attention_frame = (self.audiocomm_gizmo_pos[0]-self.audiocomm_gizmo_size-0.02,self.audiocomm_gizmo_pos[0]+self.audiocomm_gizmo_size+0.02,
                                      self.audiocomm_gizmo_pos[1]+self.audiocomm_gizmo_size+0.02,self.audiocomm_gizmo_pos[1]-self.audiocomm_gizmo_size-0.02)
        self.sound_attention_frame = (self.sound_gizmo_pos[0]-self.sound_gizmo_size-0.02,self.sound_gizmo_pos[0]+self.sound_gizmo_size+0.02,
                                      self.sound_gizmo_pos[1]+self.sound_gizmo_size+0.02,self.sound_gizmo_pos[1]-self.sound_gizmo_size-0.02)

        # satellite map parameter
        self.satmap_pos = grid(3,(1,1),(2,5),'topleft')     # position of the satellite map upper left corner (aspect2d coordinates)
        self.agent_satmap_rect  = rect(grid(3,(1,1),(2,5),'topleft',sys='window'),grid(3,(1,1),(3,5),'bottomright',sys='window')) # viewport rectangle that displays the satellite map (normalized window coordinates)
        self.satellite_height = 500                         # height of the satellite map camera over the terrain (orthographic)
        self.satmap_coverage = (225,180)                    # width and height of the satellite map covered area
        self.satmap_update_interval = 4                     # in seconds

        # audio parameters
        self.vocal_communications_volume = 0.75             # volume of the vocal communication streams (was 0.55)

        # ambience sound setup
        self.ambience_sound = 'sounds\\nyc_amb2.wav'        # sound file of the background ambience loop
        self.ambience_volume = 0.1                          # normalized volume of the ambience loop

        # overall button parameters
        self.button_framesize = (-1.5,1.5,-0.65*1.5+0.25,0.65*1.5+0.25) # size of the buttons (xmin,xmax,ymin,ymax)
        self.button_scale = 0.07*0.8                                    # scale of the buttons (scales the framesize, too)

        # response buttons for satmap task (right outer screen)
        self.right_button_colors = ['red','green','blue','yellow']        # labels for the color buttons
        self.right_button_directions = ['west','north','south','east']    # labels for the direction buttons
        self.right_button_x_offsets = [grid(3,(1,5)),grid(3,(2,5)),grid(3,(3,5)),grid(3,(4,5))]   # x offsets for the buttons, in aspect2d coordinates
        self.right_button_y_offsets = [grid(3,(),(9,10),ma=0.0125), grid(3,(),(10,10),ma=0.0125)] # y offssetss for the two rows of buttons, in aspect2d coordinate
        self.right_button_skip_pos = grid(3,(5,5),(5,5))
        self.right_button_skip_framesize = (-1.5*0.8,1.5*0.8,-1.5*1.4+0.25,1.5*1.4+0.25)  # size of the buttons (xmin,xmax,ymin,ymax)
        self.right_button_skip_scale = 0.07                                               # scale of the buttons (scales the framesize, too)

        # response buttons for the driving / object reporting and text comprehension tasks (left outer screen)
        self.left_button_sides = ['left','right','report']          # labels for the street side buttons
        self.left_button_yesno = ['yes','no','skip']                # labels for the yes/no buttons
        self.left_button_x_offsets = [grid(1,(2,5)),grid(1,(3,5)),grid(1,(4,5))] # x offsets for the buttons, in aspect2d coordinates
        self.left_button_y_offsets = [grid(3,(),(9,10),ma=0.0125),grid(3,(),(10,10),ma=0.0125)] # y offssetss for the two rows of buttons, in aspect2d coordinate

        # subtask argument overrides
        self.overall_score_args = {# display params                 # arguments for the overall score counter
                                   'bar_rect':rect(grid(2,(2,5),(1,10),'topleft',ma=0.0125),grid(2,(4,5),(1,10),'bottomright',ma=0.0125)), # rectangle for the score display bar
                                   # score parameters are scaled to a 2x as large range for the overall score (since everything adds into this)
                                   'initial_score':100,             # the initial score
                                   'maximum_level':200,             # this is the highest level that can be graphically indicated
                                   'critical_level':50              # for completeness (lockdown doesn't apply to overall score)
                                   }
        self.satmap_score_args = {# display params                  # arguments for the satmap task score counter
                                   'bar_rect':rect(grid(3,(2,5),(2,10),'topleft',ma=0.0125),grid(3,(4,5),(2,10),'bottomright',ma=0.0125)),  # rectangle for the score display bar
                                   # score parameters are scaled down a bit
                                   'initial_score':33,              # the initial score
                                   'maximum_level':66,              # this is the highest level that can be graphically indicated
                                   'critical_level':15              # for completeness (lockdown doesn't apply to overall score)
                                 }
        self.viewport_score_args = {# display params                # arguments for the viewport tasks score counter
                                  'bar_rect':rect(grid(2,(2,5),(2,10),'topleft',ma=0.0125),grid(2,(4,5),(2,10),'bottomright',ma=0.0125)),  # rectangle for the score display bar
                                  # score parameters are scaled down a bit
                                  'initial_score':33,               # the initial score
                                  'maximum_level':66,               # this is the highest level that can be graphically indicated
                                  'critical_level':15               # for completeness (lockdown doesn't apply to overall score)
        }
        self.sound_score_args = {# display params                   # arguments for the sound score counter
                                 'bar_rect':rect(grid(1,(2,10),(3,10),'topleft',ma=0.0125),grid(1,(5,10),(3,10),'bottomright',ma=0.0125)), # rectangle for the score display bar
                                 # score parameters are scaled down a bit
                                 'initial_score':33,                # the initial score
                                 'maximum_level':66,                # this is the highest level that can be graphically indicated
                                 'critical_level':15                # for completeness (lockdown doesn't apply to overall score)
        }
        self.audiocomm_score_args = {# display params               # arguments for the audio comms score counter
                                    'bar_rect':rect(grid(1,(6,10),(3,10),'topleft',ma=0.0125),grid(1,(9,10),(3,10),'bottomright',ma=0.0125)), # rectangle for the score display bar
                                    # score parameters are scaled down a bit
                                    'initial_score':33,             # the initial score
                                    'maximum_level':66,             # this is the highest level that can be graphically indicated
                                    'critical_level':15             # for completeness (lockdown doesn't apply to overall score)
        }
        self.textcomm_score_args = {# display params                # arguments for the text comms score counter
                                    'bar_rect':rect(grid(1,(2,5),(4,10),'topleft',ma=0.0125),grid(1,(4,5),(4,10),'bottomright',ma=0.0125)), # rectangle for the score display bar
                                    # score parameters are scaled down a bit
                                    'initial_score':33,             # the initial score
                                    'maximum_level':66,             # this is the highest level that can be graphically indicated
                                    'critical_level':15             # for completeness (lockdown doesn't apply to overall score)
        }

        self.stress_task_args = {}                          # arguments for the stress modulation process
        self.query_presenter_args = {}                      # arguments for the query presentation
        self.warning_light_args = {# presentation params    # arguments for the warning light task
                                   'pic_params':{'pos':self.warn_pos,'scale':self.warn_size}, # parameters for the picture() command
                                   'snd_params':{'volume':0.3,'direction':0.0},   # parameters for the sound command
                                   }
        self.text_comm_task_args = {}                       # arguments for the textual communications task
        self.audio_comm_task_args = {}                      # arguments for the audio communications task
        self.satmap_task_args = {}                          # arguments for the satellite map task
        self.sound_task_args = {# diable one of the channels # arguments for the sound task
                                # 'sound_directions' : {'front':0, 'left':-0.707, 'back':1.414} if self.num == 0 else {'front':0, 'right':0.707, 'back':1.414}
                                'sound_directions' : {'left':-1, 'right':1}
                                }
        self.attention_set_args = {}                        # arguments for the attention set management

        # --- local gamestate ---

        self.conn = None                                    # connection to the remote SNAP instance
        self.agents = []                                    # local copies of the two agents
        self.agent_gizmos = []                              # gizmos shown for the agents on the satmap
        self.update_agents_poshpr = []                      # a function (per agent) that is called to update its state        
        self.update_agent_gizmos = []                       # a function (per agent gizmo) that is called to update its state
        self.satmap_viewport = None                         # a viewport for the satellite map 

        self.text_instruction_presenter = None              # widget through which textual task instructions are being presented
        self.text_communications_presenter = None           # widget through which textual task communications are being presented
        self.vocal_communications_presenter = None          # widget through which vocal task communications are being presented
        self.score_presenter = None                         # widget through which scores are presented
        self.remote_stimpresenter = None                    # the BasicStimuli instance on the other end

        # axial control state
        self.axis_x = 0.0                                   # these are overridden by each joystick event
        self.axis_y = 0.0                                   # the values are normalized between (-1 .. +1)
        self.axis_u = 0.0
        self.axis_v = 0.0
        self.braking = False                                # whether the brake button is currently engaged
        self.previous_handbrake_button = False              # whether the handbrake button was on in the previous handler call
        self.handbrake_engaged = False                      # whether the handbrake is currently engaged
        self.push_to_talk = False                           # whether the push-to-talk button is currently engaged
        self.previous_push_to_talk = False

        # per-client scoring
        self.overall_score = None                           # this object handles the score counting

        # per-client overlay tasks         
        self.text_comm_task = None                          # textual communications task
        self.vocal_comm_task = None                         # vocal communications task        


    # ======================================
    # === GUI AND SUBTASK INITIALIZATION ===
    # ======================================

    @livecoding
    def init_gui(self):
        """
        Initialize the GUI elements that remain on screen for the whole experiment.
        """

        # start city ambient sound
        self.ambience = self.sound(self.ambience_sound,looping=True,volume=self.ambience_volume,direction=0)
        # initialize camera and 3d viewport
        self.init_viewport()
        # initialize static GUI symbols (as stand-ins for the tasks)
        self.init_static_gui_symbols()
        # initialize communication channels (text, audio, etc)
        self.init_comm_channels()
        # initialize attention indicator lamps for various tasks
        self.init_attention_indicators()
        # initialize touch-screen response buttons
        self.init_touch_buttons()
        # set up event handler
        self.eventwatcher = EventWatcher.EventWatcher(defaultevent="r-cl"+str(self.num)+"-down")
        # prepare the satellite map but don't show it yet
        self.init_satmap_setup()

    @livecoding
    def init_viewport(self):
        """ Set up camera and 3d viewport. """
        # create a camera that is attached to the agent
        self.agent_camera = rpyc.enable_async_methods(self._engine.pandac.NodePath(self._engine.pandac.Camera('world_camera')))
        self.agent_camera.reparentTo(self.agents[self.num].find("**/*Cam*"))
        self.agent_camera.setP(90)
        self.agent_camera.setZ(self.agent_camera.getZ()+self.master.vehicle_camera_plane_shift)
        # set up the lens
        camnode = rpyc.enable_async_methods(self.agent_camera.node())
        camnode.getLens().setNear(0.5)
        camnode.getLens().setFov(self.master.camera_fov)
        # set up special visibility rules
        camnode.setCameraMask(self._engine.pandac.BitMask32.bit(self.num+3))
        self.agents[self.num].hide(self._engine.pandac.BitMask32.bit(self.num+3))
        # make a viewport for the camera
        self.agent_viewport = self.create_viewport(self.agent_viewport_rect,self.agent_camera)

    @livecoding
    def init_static_gui_symbols(self):
        """ Initialize static GUI symbols (as stand-ins for the tasks). """
        # for auditory comm chatter
        self.audiocomm_gizmo = rpyc.enable_async_methods(self._engine.direct.gui.OnscreenImage.OnscreenImage(
            image = self.audiocomm_gizmo_pic,
            pos=(self.audiocomm_gizmo_pos[0],0,self.audiocomm_gizmo_pos[1]),
            scale=self.audiocomm_gizmo_size))
        self.audiocomm_gizmo.setTransparency(TransparencyAttrib.MAlpha)
        # for sound effects channel
        self.sound_gizmo = rpyc.enable_async_methods(self._engine.direct.gui.OnscreenImage.OnscreenImage(
            image = self.sound_gizmo_pic,
            pos=(self.sound_gizmo_pos[0],0,self.sound_gizmo_pos[1]),
            scale=self.sound_gizmo_size))
        self.sound_gizmo.setTransparency(TransparencyAttrib.MAlpha)

        # put in the mission briefing indicator
        self.mission_text = rpyc.enable_async_methods(self.conn.modules.framework.ui_elements.TextPresenter.TextPresenter(
            pos=self.missiontext_instructions_pos,width=self.missiontext_instructions_width,textcolor=(1,1,1,1),framecolor=(0.25,0.25,0.25,1)))

    @livecoding
    def init_comm_channels(self):
        """ Initialize communication channels (text, audio, etc). """
        # instructions screen for the viewport task
        self.viewport_instructions = rpyc.enable_async_methods(self.conn.modules.framework.ui_elements.ScrollPresenter.ScrollPresenter(
            pos=self.viewport_instructions_pos,width=self.viewport_instructions_width,textcolor=(1,1,1,1)))
        # instruction screen for the satellite map
        self.satmap_instructions = rpyc.enable_async_methods(self.conn.modules.framework.ui_elements.ScrollPresenter.ScrollPresenter(
            pos=self.satmap_instructions_pos,width=self.satmap_instructions_width,textcolor=(1,1,1,1)))
        # stress level indicator image
        self.stress_indicator = rpyc.enable_async_methods(self.conn.modules.framework.ui_elements.ImagePresenter.ImagePresenter(
            pos=self.stress_pos,scale=self.stress_size))
        # textbox for text communications (radio chatter)
        self.text_communications_presenter = rpyc.enable_async_methods(self.conn.modules.framework.ui_elements.ScrollPresenter.ScrollPresenter(
            pos=self.comm_message_pos,width=self.comm_message_width,numlines=self.comm_message_height,scale=0.025,prompt = "           > "))
        # audio presenter for auditory comm chatter
        self.vocal_communications_presenter = rpyc.enable_async_methods(self.conn.modules.framework.ui_elements.AudioPresenter.AudioPresenter(
            direction=0.0,volume=self.vocal_communications_volume))

    @livecoding
    def init_attention_indicators(self):
        """ Initialize attention indicator lamps for various tasks. """

        # attention indicator frames
        self.text_attention_indicator = rpyc.enable_async_methods(self.remote_stimpresenter.frame(self.text_attention_frame,duration=max_duration,block=False,color=(0,0,0,0)))
        self.viewport_attention_indicator = rpyc.enable_async_methods(self.remote_stimpresenter.frame(self.viewport_attention_frame,duration=max_duration,block=False,color=(0,0,0,0)))
        self.satmap_attention_indicator = rpyc.enable_async_methods(self.remote_stimpresenter.frame(self.satmap_attention_frame,duration=max_duration,block=False,color=(0,0,0,0)))
        self.vocal_attention_indicator = rpyc.enable_async_methods(self.remote_stimpresenter.frame(self.vocal_attention_frame,duration=max_duration,block=False,color=(0,0,0,0)))
        self.sound_attention_indicator = rpyc.enable_async_methods(self.remote_stimpresenter.frame(self.sound_attention_frame,duration=max_duration,block=False,color=(0,0,0,0)))

        # functions to modulate the scalar visibility (0-1) of the attention indicators
        self.text_attention_indicator_funcs = lambda x: self.text_attention_indicator.setColor(1,1,1,x)
        self.vocal_attention_indicator_funcs = lambda x: self.vocal_attention_indicator.setColor(1,1,1,x)
        self.sound_attention_indicator_funcs = lambda x: self.sound_attention_indicator.setColor(1,1,1,x)
        self.viewport_attention_indicator_funcs = lambda x: self.viewport_attention_indicator.setColor(1,1,1,x)
        self.satmap_attention_indicator_funcs = lambda x: self.satmap_attention_indicator.setColor(1,1,1,x)

    @livecoding
    def init_touch_buttons(self):
        """ Initialize touch-screen response buttons. """
        self.buttons = []
        # add color buttons
        for x in range(len(self.right_button_x_offsets)):
            self.buttons.append(rpyc.enable_async_methods(self._engine.direct.gui.DirectButton.DirectButton(
                command=rpyc.async(self.on_button),extraArgs=[self.right_button_colors[x]],rolloverSound=None,clickSound=None,
                pos=(self.right_button_x_offsets[x],0,self.right_button_y_offsets[0]),frameSize=self.button_framesize,text=self.right_button_colors[x],scale=self.button_scale)))
        # add direction buttons
        for x in range(len(self.right_button_x_offsets)):
            self.buttons.append(rpyc.enable_async_methods(self._engine.direct.gui.DirectButton.DirectButton(
                command=rpyc.async(self.on_button),extraArgs=[self.right_button_directions[x]],rolloverSound=None,clickSound=None,
                pos=(self.right_button_x_offsets[x],0,self.right_button_y_offsets[1]),frameSize=self.button_framesize,text=self.right_button_directions[x],scale=self.button_scale)))
        # add skip button
        self.buttons.append(rpyc.enable_async_methods(self._engine.direct.gui.DirectButton.DirectButton(
            command=rpyc.async(self.on_button),extraArgs=['skip'],rolloverSound=None,clickSound=None,
            pos=(self.right_button_skip_pos[0],0,self.right_button_skip_pos[1]),frameSize=self.right_button_skip_framesize,text='skip',scale=self.right_button_skip_scale)))
        # add left/right/report buttons
        for x in range(len(self.left_button_x_offsets)):
            self.buttons.append(rpyc.enable_async_methods(self._engine.direct.gui.DirectButton.DirectButton(
                command=rpyc.async(self.on_button),extraArgs=[self.left_button_sides[x]],rolloverSound=None,clickSound=None,
                pos=(self.left_button_x_offsets[x],0,self.left_button_y_offsets[0]),frameSize=self.button_framesize,text=self.left_button_sides[x],scale=self.button_scale)))
        # add yes/no/skip buttons
        for x in range(len(self.left_button_x_offsets)):
            self.buttons.append(rpyc.enable_async_methods(self._engine.direct.gui.DirectButton.DirectButton(
                command=rpyc.async(self.on_button),extraArgs=[self.left_button_yesno[x]],rolloverSound=None,clickSound=None,
                pos=(self.left_button_x_offsets[x],0,self.left_button_y_offsets[1]),frameSize=self.button_framesize,text=self.left_button_yesno[x],scale=self.button_scale)))
        # add invisible warning light button
        btn = rpyc.enable_async_methods(self._engine.direct.gui.DirectButton.DirectButton(
            command=rpyc.async(self.send_message),extraArgs=['space-'+self.tag+'-down'],rolloverSound=None,clickSound=None,
            pos=(self.warn_pos[0],0,self.warn_pos[1]),frameSize=(-self.warn_size,self.warn_size,-self.warn_size,self.warn_size),text='',text_fg=(0,0,0,0),text_bg=(0,0,0,0),frameColor=(0,0,0,0)))
        self.buttons.append(btn)
        btn.setTransparency(TransparencyAttrib.MAlpha)


    @livecoding
    def init_subtasks(self):
        """ Start the side tasks for this client. """

        # create various score counters
        self.overall_score=ScoreCounter(stimpresenter=self.remote_stimpresenter, score_log=self.master.scorelog, 
            counter_name='Overall', client_idx=self.num, bar_vertical_squish=1, **self.overall_score_args)
        self.satmap_score=ScoreCounter(stimpresenter=self.remote_stimpresenter, score_log=self.master.scorelog, 
            counter_name='Satmap', client_idx=self.num, text_color=(1,1,1,0), dependent_score=self.overall_score, **self.satmap_score_args)
        self.viewport_score=ScoreCounter(stimpresenter=self.remote_stimpresenter, score_log=self.master.scorelog, 
            counter_name='Viewport', client_idx=self.num, text_color=(1,1,1,0), dependent_score=self.overall_score, **self.viewport_score_args)
        self.text_comm_score=ScoreCounter(stimpresenter=self.remote_stimpresenter, score_log=self.master.scorelog, 
            counter_name='Text', client_idx=self.num, text_color=(1,1,1,0), dependent_score=self.overall_score, **self.textcomm_score_args)
        self.audio_comm_score=ScoreCounter(stimpresenter=self.remote_stimpresenter, score_log=self.master.scorelog, 
            counter_name='Chatter', client_idx=self.num, text_color=(1,1,1,0), dependent_score=self.overall_score, **self.audiocomm_score_args)
        self.sounds_score=ScoreCounter(stimpresenter=self.remote_stimpresenter, score_log=self.master.scorelog, 
            counter_name='Sounds', client_idx=self.num, text_color=(1,1,1,0), dependent_score=self.overall_score, **self.sound_score_args)

        # a stress modulation process (flips between high and low stress, keeps an indicator icon updated) 
        self.stress_task = self.launch(StressTask(iconpresenterfunc=self.stress_indicator.submit, client_idx=self.num, **self.stress_task_args))

        # the object responsible for presenting queries to the subject
        self.querypresenter = QueryPresenter(
            presenterfuncs = {'visual-viewport':[self.viewport_instructions.submit],
                              'visual-satmap':[self.satmap_instructions.submit],
                              'visual-text':[self.text_communications_presenter.submit],
                              'auditory':[self.vocal_communications_presenter.submit]},
            clearfuncs = {'visual-viewport':[self.viewport_instructions.clear],
                          'visual-satmap':[self.satmap_instructions.clear],
                          'visual-text':[self.text_communications_presenter.clear],
                          'auditory':[self.vocal_communications_presenter.clear]},
            scorecounters = {'overall':self.overall_score,
                             'satmap':self.satmap_score,
                             'viewport':self.viewport_score,
                             'textcomm':self.text_comm_score,
                             'audiocomm':self.audio_comm_score,
                             'sounds':self.sounds_score},
            default_event_prefix = self.tag+'-',
            default_query_prefix = self.id+', ',
            stimpresenter = self.remote_stimpresenter,
            client_idx = self.num, **self.query_presenter_args)

        # represents a warning light that occasionally needs to be confirmed with the space bar
        self.warning_light_task = self.launch(IndicatorLightTask(
            # general properties
            scorecounter=self.overall_score,
            stimpresenter = self.remote_stimpresenter,
            client_idx = self.num,
            focused = True,
            response_key = 'space-'+self.tag+'-down',
            **self.warning_light_args))

        # textual communications task (answer yes/no comprehension questions about text feeds)
        self.text_comm_task = self.launch(CommTask(
            presenterfunc = self.text_communications_presenter.submit,
            querypresenter = self.querypresenter,
            targetsign = self.id,
            client_idx = self.num,
            events = [self.tag+'-yes', self.tag+'-no', self.tag+'-skip'],
            focused = False,
            querydomain = 'visual-text',
            scoredomain = 'textcomm',
            stimulusdomain = 'visual',
            **self.text_comm_task_args))

        # voice communications task (answer yes/no comprehension questions about audio statements)
        self.audio_comm_task = self.launch(CommTask(
            presenterfunc = self.vocal_communications_presenter.submit,
            querypresenter = self.querypresenter,
            targetsign = self.id,
            client_idx = self.num,
            events = [self.tag+'-yes', self.tag+'-no', self.tag+'-skip'],
            focused = False,
            querydomain = 'auditory',
            scoredomain = 'audiocomm',
            stimulusdomain = 'auditory',
            **self.audio_comm_task_args))

        # satellite map task (answer questions about stimulus properties, e.g., color or shape) 
        self.satmap_task = SatmapTask(
            querypresenter = self.querypresenter,
            scorecounter = self.overall_score,
            engine = self._engine,
            scenegraph = self.city,
            local_scenegraph = self.master.city,
            util = self,
            client_idx = self.num,
            focused = False,
            querydomain='visual-satmap',
            scoredomain='satmap',
            **self.satmap_task_args)

        # sound events task (answer questions about direction of sound events)
        self.sound_task = self.launch(SoundTask(
            querypresenter = self.querypresenter,
            stimpresenter = self.remote_stimpresenter,
            client_idx = self.num,
            focused = False,
            scoredomain = 'sounds',
            **self.sound_task_args))

        # attention set management (activates a small subset of attendable regions at any given time)
        self.attention_manager = self.launch(AttentionSetManager(
            regions={'spoken sentences':[self.audio_comm_task],
                     'written sentences':[self.text_comm_task],
                     'sounds':[self.sound_task],
                     'satellite map icons':[self.satmap_task],
                     'curbside objects':[(lambda: self.master.worldmap_task.set_focused(self.num,False), lambda: self.master.worldmap_task.set_focused(self.num,True))]},
            instructors={'spoken sentences':self.vocal_communications_presenter.submit,
                         'written sentences':self.viewport_instructions.submit,
                         'sounds':self.vocal_communications_presenter.submit,
                         'satellite map icons':self.satmap_instructions.submit,
                         'curbside objects':self.viewport_instructions.submit},
            indicators={'spoken sentences':self.vocal_attention_indicator_funcs,
                        'written sentences':self.text_attention_indicator_funcs,
                        'sounds':self.sound_attention_indicator_funcs,
                        'satellite map icons':self.satmap_attention_indicator_funcs,
                        'curbside objects': self.viewport_attention_indicator_funcs},
            available_subset = self.master.available_attention_set,
            client_idx = self.num,
            client_id = self.id,
            **self.attention_set_args))


    # ==============================
    # === SATELLITE MAP HANDLING ===
    # ==============================

    @livecoding
    def init_satmap_setup(self):
        """
        Prepare the satellite map setup, i.e., camera, lens, special gizmos, etc., without showing the map just yet.
        """
        # create a new orthographic camera for the satmap
        self.satmap_camera = rpyc.enable_async_methods(self._engine.pandac.NodePath(self._engine.pandac.Camera('satmap_camera')))
        self.satmap_camera.reparentTo(self.city)
        camnode = rpyc.enable_async_methods(self.satmap_camera.node())
        camnode.setCameraMask(self._engine.pandac.BitMask32.bit(self.num))
        lens = rpyc.enable_async_methods(self._engine.pandac.OrthographicLens())
        lens.setFilmSize(self.satmap_coverage[0], self.satmap_coverage[1])
        camnode.setLens(lens)

        # position it appropriately
        agent_pos = self.master.agents[self.num].getPos()
        self.satmap_camera.setPos(agent_pos.getX(),agent_pos.getY(),agent_pos.getZ()+self.satellite_height)
        self.satmap_camera.setHpr(-90,-90,0)
        self.satmap_camera_setpos = self.satmap_camera.setPos

        # set camera masks
        for c in range(2):
            # ensure that the agents objects themselves are not seen by any of the satmap cameras
            # (note: generally the scene graph on the client machine has
            for a in range(2):
                self.agents[a].hide(self._engine.pandac.BitMask32.bit(c))

        # start the periodic update task
        taskMgr.doMethodLater(self.satmap_update_interval,self.update_satmap,'Update Satmap')

    @livecoding
    def toggle_satmap(self,show=True):
        """
        Toggle the satmap visibility.
        """
        if show and self.satmap_viewport is None:
            self.satmap_viewport = self.create_viewport(self.agent_satmap_rect,self.satmap_camera)
        elif not show and not (self.satmap_viewport is None):
            self._engine.base.win.removeDisplayRegion(self.satmap_viewport)
            self.satmap_viewport = None
        self.marker('Experiment Control/Task/Satellite Map/%s, Participant/ID/%i' % ('Enabled' if show else 'Disabled', self.num))

    @livecoding
    def update_satmap(self,task):
        """
        Periodically called to re-center the satellite map around the agent and update any icon content. 
        This is deliberately infrequent.
        """
        if self.satmap_viewport is not None:
            self.marker('Experiment Control/Task/Satellite Map/Update, Participant/ID/%i' % self.num)
            agent_pos = self.master.agents[self.num].getPos(self.master.city)
            # update the postion of the camera itself
            self.satmap_camera_setpos(agent_pos.getX(),agent_pos.getY(),agent_pos.getZ()+self.satellite_height)
            # calc updated the gizmo clamp box (used to clamp widgets at the borders)
            centerpos = (agent_pos.getX(),agent_pos.getY(),agent_pos.getZ())
            clampbox = (centerpos[0]-(self.satmap_coverage[1]/2-self.icon_clamp_distance),centerpos[0]+(self.satmap_coverage[1]/2-self.icon_clamp_distance),
                        centerpos[1]-(self.satmap_coverage[0]/2-self.icon_clamp_distance),(centerpos[1]+self.satmap_coverage[0]/2-self.icon_clamp_distance),
                        centerpos[2]-100,centerpos[2]+100)
            # update the checkpoint clamping
            if self.master.checkpoint:
                self.master.checkpoint.update_satmap_clamp_box(self.num,clampbox)
            # update the position and clamping of the agent gizmos
            for k in range(len(self.master.agents)):
                gizmo = self.master.agent_gizmos[k]
                gizmo.update_satmap_clamp_box(self.num,clampbox)
                pos = self.master.agents[k].getPos(self.master.city)
                hpr = self.master.agents[k].getParent().getHpr(self.master.city)
                gizmo.move_to((pos.getX(),pos.getY(),pos.getZ()+100),(0,-90,180-hpr.getX()))
            # update the satmap task
            self.satmap_task.update(self.master.agents[self.num].getPos(self.master.city))
        return task.again

    def update_terrain():
        xyz = self.agents[self.num].getPos(self.terrain_root)
        rpyc.async(self.terrain.setFocalPoint)(xyz.getX(),xyz.getY())
        rpyc.async(self.terrain.update)()

    # =================================
    # === CONNECT TO REMOTE MACHINE ===
    # =================================

    @livecoding
    def connect(self):
        """Try to connect to the remote machine/instance for this client. """
        while True:
            try:
                print 'Trying to connect to ' + self.hostname + ':' + str(self.port) + '...',
                # connect and spawn a server thread that handles callbacks from the client machine in the background
                # (this includes keypress events, etc.)  
                self.conn = rpyc.classic.connect(self.hostname,port=self.port)
                self.callback_handler_thread = threading.Thread(target=self.conn.serve_all)
                self.callback_handler_thread.setDaemon(True)
                self.callback_handler_thread.start()
                # link remote button-press events to the local handlers on_keydown and on_keyup 
                self.conn.root.mastercallbacks(self.on_keydown,self.on_keyup,self.on_joystick,self.on_speech)
                # link the stimulus-presentation engine to the remote computer's engine
                self.set_engine(base=self.conn.builtins.base,direct=self.conn.modules.direct,pandac=self.conn.modules.pandac.PandaModules)
                # and get an instance of the remote basicstimuli instance, too
                self.remote_stimpresenter = self.conn.root.stimpresenter()
                # done.
                print "done."
                break
            except Exception,e:
                print "not successful (" + str(e) + ")"
                self.sleep(5)

    @livecoding
    def run(self):
        """
        Run the client logic. 
        Simple because almost all scheduling is managed by the Main instance or is encapsulated into sub-tasks.
        """
        self.log_setup_parameters()

        # try to connect to remote machine
        self.connect()
        # make sure that the player is ready
        if not self.master.nowait:
            self.write("Welcome. You are player " + self.id + ".\nPress the Space bar when your are ready to begin.", 'space-cl' + str(self.num) + '-up')
            self.write("Now waiting for the other player to check in...",'all-checkedin')
        # wait until terminated
        self.sleep(max_duration)


    # =============================
    # === CLIENT EVENT HANDLERS ===
    # =============================

    def is_locked_down(self):
        """ Check if the resp. subject is currently in lockdown mode (because he/she has been neglecting a side task for too long. """
        lockdown = False
        if self.satmap_task and self.satmap_task.focused and self.satmap_score.is_failure():
            lockdown = True
        if self.audio_comm_task and self.audio_comm_task.focused and self.audio_comm_score.is_failure():
            lockdown = True
        if self.text_comm_task and self.text_comm_task.focused and self.text_comm_score.is_failure():
            lockdown = True
        if self.sound_task and self.sound_task.focused and self.sounds_score.is_failure():
            lockdown = True
        return lockdown

    def on_keydown(self,keyname):
        # pass the keystroke on to the master (as keyname-cl0 or keyname-cl1)
        self.send_message(keyname + '-cl' + str(self.num) + "-down")

    def on_keyup(self,keyname):
        # pass the keystroke on to the master (as keyname-cl0 or keyname-cl1)
        self.send_message(keyname + '-cl' + str(self.num) + "-up")

    def on_joystick(self,x,y,u,v,buttons):
        # pass joystick/gamepad input up to the master
        self.axis_x = x
        self.axis_y = y
        self.axis_u = u
        self.axis_v = v
        self.braking = buttons[2]
        self.push_to_talk = buttons[3]
        self.master.on_joystick(self.num,x,y,u,v,buttons)
        if not self.push_to_talk == self.previous_push_to_talk:
            self.previous_push_to_talk = self.push_to_talk
            if self.push_to_talk:
                self.master.on_pushtotalk(self.num)

    def on_speech(self,phrase):
        self.master.on_client_speech(self.num,phrase)

    def on_button(self,word):
        self.master.on_client_speech(self.num,word,actual_speech=False)


# ===========================
# === THE LSE MAIN SCRIPT ===
# ===========================

class Main(SceneBase):
    """
    The main experiment module. This module controls the overall sequencing of the experiment, as well as  
    any experiment details that are shared between both participants, such as the logic of the individual "missions".
    It also starts any other side tasks directly or indirectly.
    """

    def __init__(self):
        """
        Initialize the module: called by the SNAP framework.
        All configuration variables set here can be overridden afterwards via study configuration (.cfg) files.
        """        
        SceneBase.__init__(self)

        # setup variables
        self.client_hosts = ['10.0.0.110:3663','10.0.0.115:3664'] # client host addresses (these are running the interaction with the two subjects)
        self.client_ids = ["Delta","Echo"]                      # client call-signs
        self.controllable_ids = ["Alpha","Bravo"]               # call-signs of voice-controllable agents  
        self.developer = True                                   # developer mode: no extra frills
        self.skip_clients = False                               # skip client check-in confirmation
        self.no_terrain = False                                  # don't load terrain
        self.nowait = True                                      # skip all confirmations

        # block structure
        self.permutation = 4                                    # permutation number; used to determine the mission mix
        self.num_blocks = 5                                     # number of experiment blocks (separated by lulls)
        self.num_missions_per_block = (4,6)                     # number of missions per block [minimum,maximum]

        # mission mix
        self.lull_mission_types = ['lull-deep']                 # possible lull missions (appear between any two blocks)
        self.coop_mission_types = ['coop-secureperimeter','coop-aerialguide','coop-movetogether']   # possible coop missions (mixed to certain fractions with indiv missions within each block)
        self.indiv_mission_types = ['indiv-drive/watch','indiv-watch/drive','indiv-pan/watch','indiv-watch/pan'] # possible indiv missions
        self.fraction_coop_per_block = (0.25,0.75)              # permitted fraction of co-op missions per block
        self.fraction_coop_total = 0.4                          # overall fraction of coop missions out of block missions
        self.max_repeat_fraction = 0.3                          # maximum fraction of successive mission pairs that consist of the same mission type
        self.mission_override = ''                              # can be used to override the current mission, e.g. for pilot testing

        # world environments
        self.world_types = ['CityMedium2']                       # the possible environments; there must be a file 'media/<name>.bam' that is the actual scene graph
        self.terrain_types = ['LSE_desertplains_flat']           # the possible terrain types
        self.agent_names = ["PlayerA","PlayerB"]                 # name of the agent objects in the world map
        self.truck_name = "Truck"                                # name of the truck entity in the world: this is used to position/find the truck location

        #self.world_types = ['LSE_Mark4_tiny_zup']               # the possible environments; there must be a file 'media/<name>.bam' that
                                                                 # is the actual scene graph and a file 'media/<name>_navmesh.bin' that is the navigation mesh for it
        #self.terrain_types = ['LSE_desertplains']               # the possible environments; there must be a file 'media/<name>_color.png' and 'media/<name>_height.png'
        #self.agent_names = ["PlayerA","PlayerB"]                # name of the agent objects in the world map file (3d model)
        #self.truck_name = "PlayerB"                             # name of the truck entity in the world: this is used to position/find the truck location

        # enabled attention set
        self.available_attention_set = ['spoken sentences','written sentences','sounds','curbside objects','satellite map icons']   # the permitted areas to which attention can be addressed

        # misc
        self.alert_sound = 'sounds/SysAlert.wav'                # the alert that is played to warn off hostile agents
        self.initial_experimenter_camera_pos = (-500,-500,500)  # initial 3d position of the experimenter's camera
        self.initial_experimenter_camera_target = (0,0,0)       # initial target (look-at) point of the experimenter's camera

        # GUI parameters
        self.viewport_rect = (0.05, 0.45, 0.9, 0.1)             # viewport rect of the experimenter
        self.cam_friction = 0.5                                 # friction coefficient for inert camera movement
        self.cam_angular_friction = 0.5                         # friction coefficient for inert camera movement
        self.cam_acceleration = 2                               # linear acceleration of the camera
        self.cam_turnrate = 1                                   # turn-rate of the camera
        self.message_pos = (0.5,-0.6)                           # position of the scroll message presenter
        self.score_pos = (1.5,0)                                # position of the score presenter
        self.checkpoint_height = 2                              # in meters above the ground
        self.camera_fov = 55                                    # in degrees: note that going too high here is risking motion sickness for the players

        # satmap icons
        self.own_agent_icon = 'icons/own_agent_icon.png'                # icon to use for the own agent (oriented)
        self.friendly_agent_icon = 'icons/friendly_agent_icon.png'      # icon to use for friendly agents (oriented)
        self.unfriendly_agent_icon = 'icons/unfriendly_agent_icon.png'  # icon to use for hostile agents (oriented)
        self.neutral_agent_icon = 'icons/neutral_agent_icon.png'        # icon to use for neutral agents (oriented)
        self.agent_icon_scale = 3.5                                     # size of the agent icons (in meters relative to ground map)
        self.checkpoint_scale_cam = 2                                   # size of the checkpoint icon
        self.checkpoint_scale_satmap = 3.5                               # size of the checkpoint icon

        # vehicular control parameters
        self.engine_force = 215                                 # force of the vehicle engine (determines max-speed, among others) (was 250)
        self.brake_force = 10                                   # force of the brakes
        self.steering_range = 33.0                              # maximum range (angle in degrees) of the steering 
        self.steering_dampspeed = 15                            # steering range reaches 1/2 its max value when speed reaches 2x this value (in Kilometers per Hour),
                                                                # to narrow steering range at higher speeds
        self.vehicle_upper_speed = 40                           # in kilometers per hour -- this is where the engine starts to top out
        self.vehicle_top_speed = 50                             # in kilometers per hour -- the engine cannot accelerate beyond this
        self.friendly_field_of_view = 90.0                      # the field of view of the agents
        self.reverse_brake_force_multiplier = 3                 # when braking via the joystick the engine force is multiplied by this

        # vehicle reset action parameters
        self.reset_torqueimpulse = 50                           # corrective torque impulse
        self.reset_linearimpulse = 1500                         # corrective upwards impulse
        self.reset_height = 1.5                                 # height at which the vehicle is dropped from the sky for a reset
        self.reset_snap_radius = 50                             # radius within which the agent position will snap to a nearest point on the navigation mesh (in meters)
        self.repeat_reset_interval = 7                          # if a reset happens within less than this many seconds from the previous one, the position will be slightly jittered
        self.repeat_reset_jitter = 3                            # maximum jitter amount in meters in case of a repeated reset (in case the subject is stuck in a hole or crevice)

        # general physics parameters
        self.physics_solver_stepsize = 0.008                    # internal clock of the physics simulation, in seconds
        self.physics_solver_max_substeps = 10                   # maximum number of sub-steps per frame done by the physics solver (determines minimum tolerable fps)
        self.gravity = 9.81                                     # gravity force

        # vehicle physics parameters
        self.vehicle_dead_zone = 0.15                           # center dead zone during vehicle control
        self.vehicle_wheel_radius = 0.083                       # radius of the wheels, in meters (note: these are tiny)
        self.vehicle_suspension_travel_cm = 10.0                # travel distance for the wheel suspension (this one is in cm)
        self.vehicle_suspension_stiffness = 40.0                # stiffness of the wheel suspension 
        self.vehicle_wheel_damping_relaxation = 2.3             # damping relaxation of the tires 
        self.vehicle_wheel_damping_compression = 4.4            # damping compression of the tires
        self.vehicle_friction_slip = 100.0                      # friction slip of the tires
        self.vehicle_wheel_roll_influence = 0.1                 # roll influence on the wheels   
        self.vehicle_wheel_lateral_offset = 0.25                # the lateral offset (left/right) of the wheels from the center of mass
        self.vehicle_wheel_longitudinal_offset = 0.4            # the longitudinal offset (front/back) of the wheels from the center of mass
        self.vehicle_wheel_vertical_offset = 0.1                # the vertical offset (up/down) of the wheel axes from the center of mass
        self.vehicle_mass = 400.0                               # mass, in kilograms, of the vehicle
        self.vehicle_chassis_size = (0.25, 0.54, 0.25)          # size (width/depth/height) of the vehicle chassis (was 0.25/0.45/0.25)
        self.vehicle_chassis_offset = (0, 0.055, 0.25)          # offset of the vehicle chassis center relative to the center of mass (was 0/0/0.25)
        self.vehicle_geometry_offset = (0,0.47,0.27)            # offset of the vehicle graphics geometry relative to the chassis (center of mass) (was 0/0.5/0.25)
        self.vehicle_camera_plane_shift = -0.35                 # shift of the camera position to compensate for undesirable near clipping
        self.vehicle_roll_friction = 0.5                        # roll friction of the vehicle (slows it down)

        # terrain collision
        self.terrain_collision_offset = 2                       # z offset of the terrain's collision mesh

        # aerial control parameters
        self.rise_time = 5                                      # time it takes a drone to ramp up the rising force from 0 to max
        self.rise_altitude = 175                                # desired altitude below to which the vehicle exerts rising force
        self.rise_force = 0                                     # the current rising force (per meter of discrepancy between current altitude and desired altitude) 
                                                                # (ramped up from 0 to max during the rise_time)
        self.rise_force_max = 4                                 # maximum rising force (per meter... -- see above)
        self.rise_force_offset = 0                              # the current offset to the rising force (ramped up from 0 to max during the rise_time)
        self.rise_force_offset_max = 100                        # maximum offset of the rising force 
        self.aerial_accel = 12000                               # horizontal acceleration of aerial vehicle
        self.aerial_turnrate = 100                              # turn-rate of aerial vehicle
        self.axis_stabilization = 100                           # axis stabililzation torque for aerial vehicle 
        self.aerial_angular_damping = 0.95                      # angular damping (air friction) of aerial vehicle 
        self.aerial_linear_damping = 0.95                       # linear damping (air friction) of aerial vehicle

        # panning control parameters
        self.pan_speed = 5                                      # speed at which the camera pans
        self.report_repeat_press_interval = 0.75                # if the report button is held down for longer than this, a second report action will be triggered
        self.panning_dead_zone = 0.15                           # center dead zone during pan-the-cam control

        # wandering agent parameters
        self.wanderer_count = 10                                # number of hostile wanderers in some of the checkpoint missions
        self.pan_wanderer_count = 7                             # number of hostile wanderers in the pan-the-cam mission
        self.hostile_minimum_distance = 30.0                    # closer than this and you are spotted
        self.hostile_field_of_view = 90.0                       # the field of view of the agents
        self.hostile_agent_head_height = 2                      # in meters, for accurate line-of-sight checks

        # invading agent parameters
        self.agent_scatter = 350                                # scatter radius around friendly agents in meters
        self.invader_count = 7                                  # total number (was: 6)

        # controllable agent parameters
        self.controllable_scatter = 10                          # spawn scatter radius aroun own agents, in meters
        self.controllable_min_spawndistance = 4                 # minimum distance from own agents
        self.relative_move_distance = 10                        # distance walked for relative movement commands, in meters
        self.controllables_max_sight = 25                       # the range at which controllable robots can warn off invading robots

        # mission control parameters
        self.checkpoint_accept_distance = 10                    # both agents must get this close within the checkpoint for it to be accepted (in meters)
        self.staytogether_max_distance = 15                     # agents must stay within this distance from each other during a 'stay-together' mission 
        self.min_reset_interval = 3                             # minimum interval between agent position resets, in seconds
        self.min_spotted_interval = 10                          # the player cannot be spotted by a given hostile more frequently than every this many seconds
        self.secure_perimeter_duration = (220,280)              # in seconds ([128,180])
        self.lull_duration = (60,120)                           # min/max duration of a lull mission
        self.panwatch_duration = (240,360)                      # duration of the pan/watch mission
        self.pancam_wanderer_range = (200,200)                  # for the pan-the-cam mission, the x/y range around the subject within which the agents navigate (in meters)
        self.checkpoint_timeout = 10*60                         # timeout for the checkpoint missions, in seconds
        self.checkpoint_count = (5,9)                           # number of checkpoints to go through
        self.checkpoint_min_distance = 50                       # minimum direct distance between any two checkpoints on a tour
        self.checkpoint_max_distance = 200                      # maximum direct distance between any two successive checkpoints on a tour
        self.report_field_of_view = 30                          # the visual angle within which an agent has to be to count as reported (on pressing the button)
        self.double_report_cutoff = 15                          # if an agent is being reported within shorter succession than this many seconds it counts as a double report
        self.potentially_visible_cutoff = 3                     # if an agent was potentially visible for longer than this, and has not been reported before it went away
                                                                # we count this as a miss
        self.short_hide_cutoff = 15                             # if an agent was hidden but was still visible less than this many seconds ago we count that as
                                                                # as a reappearance after a short hide, not a full re-encounter
        self.short_spotting_cutoff = 1.5                        # if an agent was on camera for less than this duration we count that as a short spotting, which gives
                                                                # less penalty when not reported (than if it was missed despite being in plain view for long enough)
        self.fendoff_distance = 25                              # in secure-the-perimeter, if an invader is closer than this and has eye contact with a player, it will automatically retreat (no honking necessary)
        self.warn_distance = 50                                 # in secure-the-perimeter, this is the distance within which invaders in field-fov-view respond to the warn-off button
        self.use_manual_checkpoints = False                     # use manually placed checkpoints if present in the map
        self.truck_icon = 'unit19.png'                          # icon of the truck during secure-perimeter

        # response logic
        self.max_same_modality_responses = 15                   # if subject responds more than this many times in a row in the same modality
                                                                # (either speech or button) he/she gets a penalty
        self.repeated_response_loss = -2                        # loss incurred by too many repeats
        self.repeated_response_penalty_sound = 'slap.wav'       # sound that comes with this type of penalty
        self.repeated_response_penalty_volume = 0.3             # volume of the penalty sound
        self.pancam_max_report_distance = 300                   # when reporting agents beyond this distance will be considered "too far away" (and not counted)

        # push-to-talk logic
        self.pushtotalk_sound = 'ptt_beep.wav'                  # sound heard when pressing the push-to-talk button
        self.pushtotalk_own_volume = 0.37                       # volume on own headset
        self.pushtotalk_other_volume = 0.22                     # volume on other's headset

        # worldmap task
        self.worldmap_task_params = {}                          # overrides defaults from ProbedObjectsTask

        # scoring business
        self.staytogether_penalty = -1                          # penalty for not staying together during a stay-together mission
        self.checkpoint_reach_bonus = 3                         # bonus for reaching a checkpoint
        self.spotted_penalty = -6                               # penalty for being spotted by a wandering hostile
        self.perimeter_finish_bonus = 5                         # when the perimeter task has been completed
        self.chaseaway_bonus = 1                                # bonus for chasing away a hostile just by mere presence
        self.danger_penalty = -1                                # penalty that is applied when an agent has a line-of-sight to the truck
        self.unfortunate_spotting_penalty = -1                  # penalty for being spotted by a hostile agent from behind during the secure-perimeter task
        self.threatenaway_bonus = 1                             # bonus for threatening away a hostile by means of a warning signal (horn)
        self.reset_penalty = -2                                 # penalty for using the reset button
        self.pancam_false_loss = -2                             # penalty for a false report during the pan-the-cam mission
        self.pancam_missed_loss = -1                            # penalty for a missed report during the pan-the-cam mission
        self.pancam_unseen_loss = -0.5                          # penalty for missing an unseen (outside the field of view) agent in the pan-the-cam mission
        self.pancam_spotted_gain = 1                            # gain for a correct spotting during the pan-the-cam mission
        self.pancam_double_loss = -0.25                         # penalty for double-spotting an agent that has not really disappeared yet

        # periodic score updates for certain missions
        self.movetogether_score_drain_period = 60               # period (in seconds) at which score is updated during the move-together mission (countered by reaching a checkpoint in time)
        self.movetogether_score_drain = -0.5                    # amount of score that is updated at each score update
        self.aerialguide_score_drain_period = 60                # period (in seconds) at which score is updated during the aerialguide mission (countered by reaching a checkpoint in time)
        self.aerialguide_score_drain = -0.5                     # amount of score that is updated at each score update
        self.secureperimeter_score_gain_period = 60             # period (in seconds) at which score is updated during the secure-perimeter mission (countered by making mistakes during the mission)
        self.secureperimeter_score_gain = 1                     # amount of score that is updated at each score update
        self.pancam_score_gain_period = 30                      # period (in seconds) at which score is updated during the pan-the-cam mission (countered by failing to report movements)
        self.pancam_score_gain = 1                              # amount of score that is updated at each score update
        self.indivdrive_score_drain_period = 60                 # period (in seconds) at which score is updated during the indiv-drive mission (countered by reaching a checkpoint in time)
        self.indivdrive_score_drain = -0.5                      # amount of score that is updated at each score update

        # dynamic game state
        self.scorelog = []                                      # the score log file (shared between multiple instances of ScoreCounter)
        self.clients = []                                       # instances of ClientGame; wraps and proxies the remote client session
        self.agents = []                                        # player agents in the scene graph (one per client)
        self.agent_gizmos = []                                  # list of satellite map gizmos for the agents
        self.camera = None                                      # the experimenter's flyover camera
        self.vehicles = []                                      # the agents' vehicle models (for steering and other control purposes)        
        self.checkpoints = []                                   # a list of checkpoints to iterate over (during the mission)
        self.agent_control = ['vehicle','vehicle']              # the current control scheme (either 'vehicle' or 'aerial')
        self.vehicle_idx = None                                 # index of the vehicle client (0 if both are vehicle-bound)
        self.aerial_idx = None                                  # index of the aerial client (0 if both are air-bound)
        self.static_idx = None                                  # index of the static client (0 if both are static)
        self.truck_gizmo = None

        self.wanderers = []                                     # randomly wandering agents
        self.invaders = []                                      # agents that invade a particular location (= the truck)
        self.checkpoint = None                                  # the current mission checkpoint, if any
        self.controllables = []                                 # agents that can be controlled by voice
        self.last_modality = False                              # true if the last response modality was speech
        self.same_modality_repeats = 0                          # number of successive responses in the same modality (speech versus button)
        self.last_report_press_time = [0,0]                     # last time when a player hit the report button

        # initialize the clients
        for k in [0,1]:
            self.clients.append(ClientGame(self,k))

        # initialize continuous-value streams for LSL
        self.init_lsl_playerstream()
        self.init_lsl_agentstream()

    def run(self):
        """ Top-level LSE experiment procedure. Called by SNAP. """

        # --- initialization ---
        self.marker('Experiment Control/Status/Loading')
        # make sure that the settings get logged as markers
        self.log_setup_parameters()
        # initialize window properties
        self.init_window()
        # try to connect to the clients
        self.init_connection()
        # generate the permutation of blocks to use throughout the experiment
        self.init_block_permutation()
        # initialize the world (static environment and special objects)
        self.init_static_world()
        # create the player-controlled agents
        self.init_player_agents()
        # init basic HUD/GUI/viewports for all parties
        self.init_guis()
        # initialize physics and collision detection
        self.init_physics()

        # wait until everyone is ready
        self.wait_for_humans()

        # --- enter the actual gameplay ---

        # start the side/overlay tasks
        self.init_subtasks()
        self.marker('Experiment Control/Sequence/Experiment Begins')        
        # for each experiment block b
        for b in range(self.num_blocks):
            # play back the current block 
            self.play_block(b)
        self.marker('Experiment Control/Sequence/Experiment Ends')
        self.write('Experiment finished.','space')


    # ===========================
    # === INITIALIZATION CODE ===
    # ===========================

    @livecoding
    def init_window(self):
        """ Initialize window properties. """
        winprops = WindowProperties() 
        winprops.setTitle('LSE GameServer '+server_version) 
        base.win.requestProperties(winprops)

    @livecoding
    def init_connection(self):
        self.write('This program will appear to be unresponsive while trying to connect...',1)
        for k in range(2):
            hostport = self.client_hosts[k]                                # the "hostname:port" of the client (e.g. "localhost:3663")
            self.clients[k].hostname = hostport.split(':')[0]              # hostname of the client machine (effectively a rich graphical terminal)
            self.clients[k].port = int(hostport.split(':')[1])             # port of the client machine
            self.clients[k].id = self.client_ids[k]                        # identification string (e.g. "Delta")
            self.launch(self.clients[k])
        while not (self.clients[0].conn and self.clients[1].conn):
            self.sleep(0.1)

    @livecoding
    def init_block_permutation(self):
        """ Generates a permutation of blocks for the current experiment, according to the value of self.permutation (= the permutation number). """
        print 'Generating block permutations...',
        self.nonlull_mission_types = self.coop_mission_types + self.indiv_mission_types
        self.mission_types = self.lull_mission_types + self.nonlull_mission_types
        self.num_missions_nonlull = int(self.num_blocks * (self.num_missions_per_block[0]+self.num_missions_per_block[1]) / 2.0) 
        self.num_missions_total = self.num_missions_nonlull + self.num_blocks-1 # there is a lull mission between any two blocks 

        random.seed(self.permutation*1391 + 31)
        self.marker('Experiment Control/Sequence/Permutation ID/%i' % self.permutation)

        # determine block lengths
        self.block_lengths = []
        possible_lengths = range(self.num_missions_per_block[0],self.num_missions_per_block[1]+1)        
        # make an initial guess and then adjust pseudo-randomly
        for b in range(self.num_blocks):            
            self.block_lengths.append(random.choice(possible_lengths))
        while sum(self.block_lengths) < self.num_missions_nonlull:
            idx = random.choice([i for i in range(self.num_blocks) if self.block_lengths[i] < self.num_missions_per_block[1]])
            self.block_lengths[idx] += 1
        while sum(self.block_lengths) > self.num_missions_nonlull:
            idx = random.choice([i for i in range(self.num_blocks) if self.block_lengths[i] > self.num_missions_per_block[0]])
            self.block_lengths[idx] -= 1
        self.block_indices = []
        next_index = 0
        for b in self.block_lengths:
            self.block_indices.append(range(next_index,next_index+b))
            next_index = next_index+b

        # generate an initial sequence with the correct fractions (but possibly too long)
        self.mission_order = self.coop_mission_types * int(1 + self.fraction_coop_total * self.num_missions_nonlull /
                                                           float(len(self.coop_mission_types))) + self.indiv_mission_types * int(1 + (1.0-self.fraction_coop_total) * self.num_missions_nonlull /
                                                                                                                                 float(len(self.indiv_mission_types)))
        # drop elements at random until we have the correct count
        while len(self.mission_order) > self.num_missions_nonlull:
            self.mission_order.pop(random.choice(range(len(self.mission_order))))
        # now re-balance until we have a valid mix for each block
        okay = False
        attempts = 0
        while not okay:
            attempts += 1
            random.shuffle(self.mission_order)
            okay = True
            for blockrange in self.block_indices:
                fraction_coop = len([m for m in [self.mission_order[k] for k in blockrange] if m.startswith('coop-')]) / float(len(blockrange))
                if fraction_coop < self.fraction_coop_per_block[0] or fraction_coop > self.fraction_coop_per_block[1]:
                    okay = False
                    break
                # extra constraint to prevent successive identical missions (requires more mission variety before it can be enabled)
                num_dups = 0
                for k in range(len(self.mission_order)-1):
                    # avoid the same mission twice in a row
                    if self.mission_order[k] == self.mission_order[k+1]:
                        num_dups += 1
                if num_dups * 1.0 / (len(self.mission_order)-1) > self.max_repeat_fraction:
                    okay = False
                    break
        self.block_missions = []
        for idxrange in self.block_indices:
            self.block_missions.append([self.mission_order[k] for k in idxrange])

        # now determine the ordering of lull missions
        self.lull_order = self.lull_mission_types * (1+(self.num_blocks-1) / len(self.lull_mission_types))
        while len(self.lull_order) > (self.num_blocks-1):
            self.lull_order.pop(random.choice(range(len(self.lull_order))))
        random.shuffle(self.lull_order)
        print 'done after', attempts, 'attempts.'

    @livecoding
    def wait_for_humans(self):
        """ Wait until all involved persons (subjects and experimenter) have confirmed that they are ready to begin. """
        if not self.nowait:
            self.marker('Experiment Control/Status/Waiting for Input')
            if not self.skip_clients:
                # wait until both subjects have confirmed that they are ready
                self.num_acks = 0
                self.acceptOnce('space-cl0-up',self.client_ack)
                self.acceptOnce('space-cl1-up',self.client_ack)
                while self.num_acks < len(self.clients):
                    self.sleep(0.1)
                self.send_message('all-checkedin')
            # wait for the space bar until we enter the actual game
            self.write('Press space when ready to start the game.','space',pos=(1.2,-0.4))

    @livecoding
    def init_guis(self):
        """ Initializes the task-independent (persistent) GUIs of all participants, including experimenter and subjects. """

        # add experimenter's free-floating camera and camera controls
        self.camera = NodePath(Camera('world_camera'))
        self.camera.node().setCameraMask(BitMask32.bit(2))
        self.camera.reparentTo(self.world_root)        
        self.camera.setPos(self.initial_experimenter_camera_pos[0],self.initial_experimenter_camera_pos[1],self.initial_experimenter_camera_pos[2])
        self.camera.lookAt(self.initial_experimenter_camera_target[0],self.initial_experimenter_camera_target[1],self.initial_experimenter_camera_target[2])
        self.cam_lasttime = time.time()
        self.terrain_lastupdate = 0
        self.cam_position = self.camera.getPos()
        self.cam_orientation = self.camera.getHpr()
        self.cam_velocity = Point3(0,0,0)
        self.cam_angular_velocity = Point3(0,0,0)
        taskMgr.add(self.on_camtick, "ExperimenterCamTick")

        # make a viewport for it
        self.viewport = self.create_viewport(self.viewport_rect,self.camera)

        # add text presenters
        self.message_presenter = ScrollPresenter.ScrollPresenter(pos=self.message_pos)
        self.score_presenter = TextPresenter.TextPresenter(pos=self.score_pos,framecolor=[0,0,0,0])

        # add experimenter camera controls
        self.accept('w',self.on_up); self.accept('w-repeat',self.on_up)
        self.accept('s',self.on_down); self.accept('s-repeat',self.on_down)
        self.accept('a',self.on_left); self.accept('a-repeat',self.on_left)
        self.accept('d',self.on_right); self.accept('d-repeat',self.on_right)
        self.accept('q',self.on_turnleft); self.accept('q-repeat',self.on_turnleft)
        self.accept('e',self.on_turnright); self.accept('e-repeat',self.on_turnright)
        self.accept('r',self.on_forward); self.accept('r-repeat',self.on_forward)
        self.accept('t',self.on_reverse); self.accept('t-repeat',self.on_reverse)
        self.accept('f',self.on_turnup); self.accept('f-repeat',self.on_turnup)
        self.accept('g',self.on_turndown); self.accept('g-repeat',self.on_turndown)

        # init client GUIs
        for cl in self.clients:
            cl.init_gui()

    @livecoding
    def init_static_world(self):
        """ Initialize the static world (city, terrain, skybox). """
        self.write("Initializing world...")

        # first load the static game world for everyone
        mapnum = random.choice(range(len(self.world_types)))        
        self.create_static_world(self.world_types[mapnum],None if self.no_terrain else self.terrain_types[mapnum],None,False)
        for cl in self.clients:
            cl.create_static_world(self.world_types[mapnum],None if self.no_terrain else self.terrain_types[mapnum],None,True)

        # get the position of the truck
        truck = self.city.find("**/" + self.truck_name + "*")
        self.truck_pos = truck.getPos(self.city)
        if self.waypoint_pos is None:
            self.waypoint_pos = self.truck_pos

            # parse the checkpoints from the map
        for node in self.city.findAllMatches('**/Checkpoint*-lib'):
            pos = node.getPos(self.city)
            self.checkpoints.append((node.getName(),[pos.getX(),pos.getY(),pos.getZ()+self.checkpoint_height]))
            node.removeNode()
        # sort by name...
        self.checkpoints.sort()
        # remove the name again
        self.checkpoints = [x[1] for x in self.checkpoints]

        self.write("done.")

    @livecoding
    def init_player_agents(self):
        """ Create the player-controlled agents. """
        # create the local and remote player agents (these are abstract scene nodes)
        for k in range(len(self.clients)):
            self.agents.append(self.find_agent(self.agent_names[k]))

            for cl in self.clients:
                cl.agents.append(rpyc.enable_async_methods(cl.find_agent(self.agent_names[k])))
                cl.update_agents_poshpr.append(cl.agents[k].setPosHpr)                    

            # also create the (satmap) gizmo objects for the agents
            visible_to = [0,1]
            self.agent_gizmos.append(SmartGizmo(
                display_scenegraphs=[self.clients[j].city for j in visible_to] + [self.city],
                display_funcs=[(self.clients[j].conn.modules.framework.ui_elements.WorldspaceGizmos.create_worldspace_gizmo,self.clients[j].conn.modules.framework.ui_elements.WorldspaceGizmos.destroy_worldspace_gizmo) for j in visible_to] + [(create_worldspace_gizmo,destroy_worldspace_gizmo)],
                display_engines=[self.clients[j]._engine for j in visible_to] + [self._engine],
                client_indices = visible_to + [2],
                image=[(self.own_agent_icon if j==k else self.friendly_agent_icon) for j in visible_to] + [self.friendly_agent_icon],
                scale=self.agent_icon_scale,opacity=0.95,oncamera=False,onsatmap=True,onexperimenter=False,billboard=False,throughwalls=True))

        # set up a process that broadcasts the local (dynamic) gamestate to the clients (entity positions, etc.)
        taskMgr.add(self.broadcast_gamestate,"BroadcastGamestate")
        # taskMgr.add(self.update_terrain, "UpdateTerrain") # (no need to do that if subjects don't drive over terrain)

    @livecoding
    def init_subtasks(self):
        """ Initialize the per-client and global subtasks. """
        self.scorelog = open('logs\\LSE-scoretable-%s.log' % time.asctime().replace(':','_'),'a')
        for cl in self.clients:
            cl.init_subtasks()
        self.init_global_subtasks()
        # also initialize the scores
        self.update_score_both(0)

    @livecoding
    def init_global_subtasks(self):
        """ Init the global (world-space) subtasks. """
        self.worldmap_task = self.launch(ProbedObjectsTask(
            querypresenters=[self.clients[0].querypresenter,self.clients[1].querypresenter],
            report_scorecounters=[self.clients[0].viewport_score,self.clients[1].viewport_score],
            agents = [self.agents[0],self.agents[0]],
            active_agents = [],
            display_scenegraphs = [self.city,self.clients[0].city,self.clients[1].city],
            display_funcs = [(create_worldspace_instance,destroy_worldspace_instance),
                             (self.clients[0].conn.modules.framework.ui_elements.WorldspaceGizmos.create_worldspace_instance,
                              self.clients[0].conn.modules.framework.ui_elements.WorldspaceGizmos.destroy_worldspace_instance),
                             (self.clients[1].conn.modules.framework.ui_elements.WorldspaceGizmos.create_worldspace_instance,
                              self.clients[1].conn.modules.framework.ui_elements.WorldspaceGizmos.destroy_worldspace_instance)],
            display_engines = [self._engine,self.clients[0]._engine,self.clients[1]._engine],
            scenegraph = self.city,
            navmesh = self.navcrowd.nav,
            physics = self.physics,
            querydomain='visual-viewport',
            scoredomain='viewport',
            **self.worldmap_task_params))

    # ============================
    # === MAIN TASK SCHEDULING ===
    # ============================

    @livecoding
    def play_block(self, b):
        """
        Play through the current experiment block.
        An experiment block consists of a sequence of missions followed by a lull (except in the last block, which has no lull). 
        """
        self.marker('Experiment Control/Sequence/Block Begins/%i' % b)
        blockdisplay = self.write('Current block #: ' + str(b+1) + '/' + str(self.num_blocks),pos=(-1.5,-0.975),scale=0.025,duration=max_duration,block=False)
        # for each mission in the block...
        for m in range(self.block_lengths[b]):
            missiontype = self.block_missions[b][m] if not self.mission_override else self.mission_override
            missiondisplay = self.write('Mission # within block: ' + str(m+1) + '/' + str(self.block_lengths[b]) + '; name: ' + missiontype,pos=(-1.5,-0.925),scale=0.025,duration=max_duration,block=False)
            # play the next block mission
            self.marker('Experiment Control/Sequence/Mission Begins/%s' % missiontype)
            if missiontype == 'indiv-drive/watch':
                self.play_indiv_drive_watch(['vehicle','static'])
            elif missiontype == 'indiv-watch/drive':
                self.play_indiv_drive_watch(['static','vehicle'])
            elif missiontype == 'indiv-pan/watch':
                self.play_indiv_pan_watch(['panning','static'])
            elif missiontype == 'indiv-watch/pan':
                self.play_indiv_pan_watch(['static','panning'])
            elif missiontype == 'coop-movetogether':
                self.play_coop_movetogether()
            elif missiontype == 'coop-aerialguide':
                self.play_coop_aerialguide()
            elif missiontype == 'coop-secureperimeter':
                self.play_secureperimeter()
            elif missiontype == 'indiv-freeroam':
                self.play_freeroam()
            else:
                self.write('This mission type (' + missiontype + ') has not yet been implemented.',5)
            missiondisplay.destroy()
            self.marker('Experiment Control/Sequence/Mission Ends/%s' % missiontype)
            self.broadcast_message('this mission is now over.',mission=True)
        blockdisplay.destroy()

        # play the next lull mission
        if b < len(self.lull_order):
            lulldisplay = self.write('Current lull #: ' + str(b+1) + '/' + str(self.num_blocks-1),pos=(-1.5,-0.95),scale=0.05,duration=max_duration)
            lulltype = self.lull_order[b]
            self.marker('Experiment Control/Sequence/Lull Begins/%s' % lulltype)
            if lulltype == 'lull-deep':
                self.play_lulldeep()
            else:
                self.write('This lull mission type (' + lulltype + ') has not yet been implemented.',5)
            lulldisplay.destroy()
            self.marker('Experiment Control/Sequence/Lull Ends/%s' % lulltype)
        self.marker('Experiment Control/Sequence/Block Ends/%i' % b)


    @livecoding
    def play_indiv_drive_watch(self,controlscheme):
        """
        A mission in which one subject has the checkpoint-drive/reporting task while the other is static and
        interacts only with the satellite maps and the comm displays. Both have a satellite map. 
        """
        # set up UI and control schemes
        try:
            for cl in self.clients:
                cl.toggle_satmap(True)
            self.reset_control_scheme(controlscheme,randomize=False) # TODO: remove the randomize=False when done debugging
            # disable the viewport side task
            self.clients[self.static_idx].attention_manager.mask_regions(set(self.available_attention_set).difference(['curbside objects']))
            self.clients[self.static_idx].attention_manager.load_distribution_override = lambda: random.choice([1,1,1,1,2,2,2,2])
            self.worldmap_task.active_agents = [self.vehicle_idx]
            # show instructions
            self.message_presenter.submit('Subjects are tasked with independent missions.\nOne subject is static and interacts only with the side tasks while the other subject performs a checkpoint driving task.')
            self.broadcast_message("starting now, perform the checkpoint mission on your own. Please ignore your partner for now.",mission=True,client=self.vehicle_idx)
            self.broadcast_message("starting now, please wait for your next mission; continue to do side tasks as instructed. Please ignore your partner for now.",mission=True,client=self.static_idx)
            self.sleep(5)
            # set up periodic score update
            taskMgr.doMethodLater(self.indivdrive_score_drain_period,self.update_score_periodic,'UpdateScorePeriodic',extraArgs=[self.indivdrive_score_drain,[self.vehicle_idx]], appendTask=True)
            # add checkpoint gizmo
            self.checkpoint = self.create_checkpoint(visible_to=[self.vehicle_idx],oncamera=True,onsatmap=True,throughwalls=True)
            # generate new checkpoint sequence
            if not (self.use_manual_checkpoints and self.checkpoints):
                self.checkpoints = generate_path(
                    startpos=self.waypoint_pos,
                    endpos=self.waypoint_pos,
                    num_positions=int(random.uniform(self.checkpoint_count[0],self.checkpoint_count[1])),
                    scenegraph=self.city,
                    navmesh=self.navcrowd.nav,
                    physics=self.physics,
                    objectnames=('Concrete',),
                    require_reachability=False,
                    min_distance_between_positions=self.checkpoint_min_distance,
                    max_distance_between_successive_positions=self.checkpoint_max_distance)
            # wait until the checkpoint has been reached
            for cp in range(len(self.checkpoints)):
                # move the gizmo
                pos = self.checkpoints[cp]
                self.checkpoint.move_to(pos)
                # while not succeeded...
                while (self.agents[self.vehicle_idx].getPos(self.city) - Point3(pos[0],pos[1],pos[2])).length() > self.checkpoint_accept_distance:
                    self.sleep(1)
                # checkpoint was reached
                self.marker('Experiment Control/Task/Checkpoint/Reached')
                self.clients[self.vehicle_idx].viewport_instructions.submit('You have successfully reached the checkpoint!')
                self.clients[self.vehicle_idx].overall_score.score_event(self.checkpoint_reach_bonus*self.clients[self.vehicle_idx].stress_task.stress_level)
                self.sleep(3)
        finally:
            # cleanup
            self.clients[self.static_idx].attention_manager.mask_regions(set(self.available_attention_set))
            self.clients[self.static_idx].attention_manager.load_distribution_override = None
            if self.checkpoint:
                self.checkpoint.destroy()
                self.checkpoint = None
            taskMgr.remove('UpdateScorePeriodic')

    @livecoding
    def play_indiv_pan_watch(self,controlscheme):
        """
        A mission in which one subject has a pan-the-cam task while the other is static and
        interacts only with the satellite maps and the comm displays. Both have a satellite map.
        """
        # set up UI and control schemes
        accept_message = ''
        try:
            for cl in self.clients:
                cl.toggle_satmap(True)
            self.reset_control_scheme(controlscheme,randomize=False) # TODO: remove the randomize=False when done debugging

            # determine the navigation zone around the relevant subject
            v = self.agents[self.panning_idx]
            v_pos = v.getPos(self.city)
            box_constraint = ((v_pos[0]-self.pancam_wanderer_range[0]/2,v_pos[0]+self.pancam_wanderer_range[0]/2),(v_pos[1]-self.pancam_wanderer_range[1]/2,v_pos[1]+self.pancam_wanderer_range[1]/2),(-10000,10000))

            self.create_wanderers(self.pan_wanderer_count,box_constraint=box_constraint)
            accept_message = self.clients[self.panning_idx].tag + '-report'
            self.accept(accept_message, lambda: self.on_client_report(self.panning_idx))
            # disable the viewport side tasks
            self.clients[self.panning_idx].attention_manager.mask_regions(set(self.available_attention_set).difference(['curbside objects']))
            self.clients[self.static_idx].attention_manager.mask_regions(set(self.available_attention_set).difference(['curbside objects']))
            self.clients[self.static_idx].attention_manager.load_distribution_override = lambda: random.choice([1,1,1,1,2,2,2,2])
            self.worldmap_task.active_agents = []
            # show instructions
            self.message_presenter.submit('Subjects are tasked with independent missions.\nOne subject is static and interacts only with the side tasks while the other subject has 360 degree control over a camera and reports foreign behaviors.')
            self.broadcast_message("starting now, perform the 360 degree viewing and reporting mission on your own. Please ignore your partner for now.",client=self.panning_idx,mission=True)
            self.broadcast_message("starting now, please wait for your next mission; continue to do side tasks as instructed. Please ignore your partner for now.",client=self.static_idx,mission=True)
            self.sleep(5)
            # set up periodic score update
            taskMgr.doMethodLater(self.pancam_score_gain_period,self.update_score_periodic,'UpdateScorePeriodic',extraArgs=[self.pancam_score_gain,[self.panning_idx]], appendTask=True)
            # enter main loop
            duration = random.uniform(self.panwatch_duration[0],self.panwatch_duration[1])
            tEnd = time.time() + duration
            while time.time() < tEnd:
                # get player parameters
                v = self.agents[self.panning_idx]
                v_pos = v.getPos(self.city)
                v_vec = v.getParent().getMat(self.city).getRow3(1)
                v_vec = Vec3(v_vec.getX(),v_vec.getY(),v_vec.getZ())
                c = self.panning_idx
                now = time.time()
                # for each agent...
                for a in self.wanderers:
                    a_pos = Point3(a.pos.getX(),a.pos.getY(),a.pos.getZ()+self.hostile_agent_head_height)
                    # visible on camera
                    directly_visible = line_of_sight(self.physics, v_pos, a_pos, v_vec, a.vel, src_fov=self.friendly_field_of_view) is not None
                    # has line-of-sight with player but not necessarily on camera
                    potentially_visible = line_of_sight(self.physics, v_pos, a_pos) is not None

                    # update direct visibility properties (= in field of view)
                    if a.is_directly_visible[c] != directly_visible:
                        self.marker('Experiment Control/Task/PanTheCam/Agent Becomes %s/{identifier:%i}, Participants/ID/%i' % ('Visible' if a.is_directly_visible[c] else 'Invisible',a.identifier,self.panning_idx))
                        if a.is_directly_visible[c]:
                            # agent just became visible
                            a.directly_visible_since[c] = now
                        else:
                            # agent just became invisible
                            a.was_directly_visible_for[c] = now - a.directly_visible_since[c]
                            a.directly_invisible_since[c] = now
                        a.is_directly_visible[c] = directly_visible

                    # update potential visibility properties (= visible if the cam is panned towards it)
                    if a.is_potentially_visible[c] != potentially_visible:
                        if a.is_potentially_visible[c]:
                            # agent just became visible
                            a.potentially_visible_since[c] = now
                        else:
                            # agent just became invisible
                            a.was_potentially_visible_for[c] = now - a.potentially_visible_since[c]
                            # if it has not been reported since it became potentially visible...
                            if a.last_report_time[c] > a.potentially_visible_since[c]:
                                # and it has been visible for long enough that it counts as an actual encounter (not just a short blip)
                                if a.was_potentially_visible_for[c] > self.potentially_visible_cutoff:
                                    # and the last report dates back long enough that it is not a double report
                                    if a.last_report_time[c] > self.double_report_cutoff:
                                        # and it is not just a reappearance after a short hide
                                        if a.potentially_invisible_since[c] > self.short_hide_cutoff:
                                            # then it's a genuine miss!
                                            if a.directly_visible_since[c] <= a.potentially_visible_since[c] and a.was_directly_visible_for[c] > self.short_spotting_cutoff:
                                                # and it was directly visible for long enough during this encounter to be counted as a full-visible miss
                                                self.marker('Experiment Control/Task/PanTheCam/Visible Agent Report Missed/{identifier:%i}, Participants/ID/%i' % (a.identifier,self.panning_idx))
                                                self.clients[c].overall_score.score_event(self.pancam_missed_loss)
                                            else:
                                                # it was never really in view so we don't penalize quite as badly
                                                self.marker('Experiment Control/Task/PanTheCam/Invisible Agent Report Missed/{identifier:%i}, Participants/ID/%i' % (a.identifier,self.panning_idx))
                                                self.clients[c].overall_score.score_event(self.pancam_unseen_loss)
                            a.potentially_invisible_since[c] = now
                        a.is_potentially_visible[c] = potentially_visible
                # time between updates
                self.sleep(0.25)

        finally:
            # cleanup
            self.clients[self.static_idx].attention_manager.mask_regions(set(self.available_attention_set))
            self.clients[self.static_idx].attention_manager.load_distribution_override = None
            self.clients[self.panning_idx].attention_manager.mask_regions(set(self.available_attention_set))
            self.ignore(accept_message)
            self.destroy_wanderers()
            taskMgr.remove('UpdateScorePeriodic')

    @livecoding
    def play_coop_movetogether(self):
        """
        A mission in which both subjects have a satellite map and need to move through a sequence of checkpoints.
        Both players need to reach the next checkpoint before they can move on, and generally they should stay within 
        no more than a certain range from each other. 
        """
        try:
            # set up UI and control schemes
            for cl in self.clients:
                cl.toggle_satmap(True)
            self.reset_control_scheme(['vehicle','vehicle'])
            # both agents get the worldmap task
            self.worldmap_task.active_agents = [0,1]
            # generate new checkpoint sequence
            if not (self.use_manual_checkpoints and self.checkpoints):
                self.checkpoints = generate_path(
                    startpos=self.waypoint_pos,
                    endpos=self.waypoint_pos,
                    num_positions=int(random.uniform(self.checkpoint_count[0],self.checkpoint_count[1])),
                    scenegraph=self.city,
                    navmesh=self.navcrowd.nav,
                    physics=self.physics,
                    objectnames=('Concrete',),
                    require_reachability=False,
                    min_distance_between_positions=self.checkpoint_min_distance,
                    max_distance_between_successive_positions=self.checkpoint_max_distance)
            # show the instructions
            self.broadcast_message('starting now, perform the cooperative checkpoint mission with your partner.',mission=True)
            self.sleep(5)
            # set up periodic score update
            taskMgr.doMethodLater(self.movetogether_score_drain_period,self.update_score_periodic,'UpdateScorePeriodic',extraArgs=[self.movetogether_score_drain,[0,1]], appendTask=True)
            # show gizmo on all clients
            self.checkpoint = self.create_checkpoint(visible_to=[0,1],oncamera=True,onsatmap=True,throughwalls=True)
            # wait until the checkpoint has been reached
            for cp in range(len(self.checkpoints)):
                # move the checkpoint
                pos = self.checkpoints[cp]
                self.checkpoint.move_to(pos)
                # while not succeeded...
                while ((self.agents[0].getPos(self.city) - Point3(pos[0],pos[1],pos[2])).length() > self.checkpoint_accept_distance) or \
                      ((self.agents[1].getPos(self.city) - Point3(pos[0],pos[1],pos[2])).length() > self.checkpoint_accept_distance):
                    # check if the agents are in fact staying together
                    distance = (self.agents[0].getPos(self.city) - self.agents[1].getPos(self.city)).length() 
                    if  distance > self.staytogether_max_distance:
                        self.marker('Experiment Control/Task/Hints/Agents Stay Together')
                        self.broadcast_message('your vehicles need to stay together!')
                        self.update_score_both(self.staytogether_penalty)
                        self.sleep(5)
                    # check again in a second
                    self.sleep(1)
                # checkpoint was reached
                self.marker('Experiment Control/Task/Checkpoint/Reached')
                self.broadcast_message('you have successfully reached the checkpoint!')
                self.update_score_both(self.checkpoint_reach_bonus)
                self.sleep(3)
        finally:
            # cleanup
            if self.checkpoint:
                self.checkpoint.destroy()
                self.checkpoint = None
            taskMgr.remove('UpdateScorePeriodic')

    @livecoding
    def play_coop_aerialguide(self):
        """
        A mission in which one subject has a satellite map and an unmanned aerial vehicle (UAV) and the other subject has a robotic vehicle.
        The aerial subject guides the ground-based subject through a sequence of checkpoints (full situational overview is only available to the
        aerial player). The ground-based subject shall furthermore avoid freely navigating hostile agents (Wanderers).
        """
        try:
            # set up UI and control schemes
            self.create_wanderers(self.wanderer_count)
            self.reset_control_scheme(['vehicle','aerial'])
            self.clients[self.vehicle_idx].toggle_satmap(False)
            self.clients[self.aerial_idx].toggle_satmap(True)
            # disable the viewport side task for the aerial subject and satmap side tasks for driving subject
            self.clients[self.aerial_idx].attention_manager.mask_regions(set(self.available_attention_set).difference(['curbside objects']))
            self.clients[self.vehicle_idx].attention_manager.mask_regions(set(self.available_attention_set).difference(['satellite map icons']))
            self.worldmap_task.active_agents = [self.vehicle_idx]
            # display instructions for everyone
            self.message_presenter.submit('One of the players now guides the other through the map from an aerial perspective.')
            self.broadcast_message("starting now, perform the aerial guidance mission with your partner. Follow your partner's instructions.",client=self.vehicle_idx,mission=True)
            self.broadcast_message('starting now, perform the aerial guidance mission with your partner. Guide your partner through the checkpoints.',client=self.aerial_idx,mission=True)
            self.sleep(5)
            # generate new checkpoint sequence
            if not (self.use_manual_checkpoints and self.checkpoints):
                self.checkpoints = generate_path(
                    startpos=self.waypoint_pos,
                    endpos=self.waypoint_pos,
                    num_positions=int(random.uniform(self.checkpoint_count[0],self.checkpoint_count[1])),
                    scenegraph=self.city,
                    navmesh=self.navcrowd.nav,
                    physics=self.physics,
                    objectnames=('Concrete',),
                    require_reachability=False,
                    min_distance_between_positions=self.checkpoint_min_distance,
                    max_distance_between_successive_positions=self.checkpoint_max_distance)
            # set up periodic score update
            taskMgr.doMethodLater(self.aerialguide_score_drain_period,self.update_score_periodic,'UpdateScorePeriodic',extraArgs=[self.aerialguide_score_drain,[0,1]], appendTask=True)
            # move the agent up into the air (by gradually ramping up the force)
            t0 = time.time()
            while True:
                fraction = (time.time() - t0) / self.rise_time                                    
                if fraction > 1.0:
                    break
                self.rise_force = self.rise_force_max * fraction
                self.rise_force_offset = self.rise_force_offset_max * fraction
                self.sleep(0.05)                                     
            # add checkpoint gizmos for the players (but the vehicle player does not get to see them through walls)
            self.checkpoint = self.create_checkpoint(visible_to=[self.vehicle_idx,self.aerial_idx],oncamera=True,onsatmap=True,throughwalls=[False,True,True])
            # for each checkpoint...
            for cp in range(len(self.checkpoints)):
                # move the checkpoint
                pos = self.checkpoints[cp]
                self.checkpoint.move_to(pos)
                # while not succeeded...
                while True:
                    vehicle_pos = self.agents[self.vehicle_idx].getPos(self.city)
                    # check if we've reached the checkpoint
                    if (vehicle_pos - Point3(pos[0],pos[1],pos[2])).length() < self.checkpoint_accept_distance:
                        break
                    # check if we bumped into a hostile
                    for a in self.wanderers:
                        a_pos = Point3(a.pos.getX(),a.pos.getY(),a.pos.getZ()+2) # the agent's head is not on ground level
                        if line_of_sight(self.physics, a_pos, vehicle_pos, a.vel, src_maxsight=self.hostile_minimum_distance, src_fov=self.hostile_field_of_view) is not None and (time.time() - a.last_spotting_time[self.vehicle_idx]) > self.min_spotted_interval:
                            a.last_spotting_time[self.vehicle_idx] = time.time()
                            self.marker('Experiment Control/Task/Hint/Spotted By Hostile Wanderer')
                            self.clients[self.vehicle_idx].viewport_instructions.submit(self.clients[self.vehicle_idx].id + ', you have been spotted by a foreign drone!')
                            self.clients[self.aerial_idx].viewport_instructions.submit(self.clients[self.aerial_idx].id + ', your partner has been spotted by a foreign drone!')
                            self.update_score_both(self.spotted_penalty)
                            self.sleep(2)
                    # check again shortly
                    self.sleep(0.25)
                # checkpoint was reached
                self.marker('Experiment Control/Task/Checkpoint/Reached')
                self.broadcast_message('you have successfully reached the checkpoint!')
                self.update_score_both(self.checkpoint_reach_bonus)
                self.sleep(3)
        finally:
            # cleanup
            self.clients[self.aerial_idx].attention_manager.mask_regions(set(self.available_attention_set))
            self.clients[self.vehicle_idx].attention_manager.mask_regions(set(self.available_attention_set))
            if self.checkpoint:
                self.checkpoint.destroy()
                self.checkpoint = None
            self.destroy_wanderers()
            taskMgr.remove('UpdateScorePeriodic')

    @livecoding
    def play_secureperimeter(self):
        """
        A mission in which both subjects have a drivable robotic vehicle and voice control over two further robotic assets. The task
        of the subjects is to secure the perimeter around a central high-value location ("the truck") against inbound hostile agents.
        The agents are threatened away by mere presence of your four robots (but can come from various angles) or by an explicit warning 
        call that can be triggered via a button on the gamepad.
        """
        try:
            # reset UI and control schemes
            for cl in self.clients:
                cl.toggle_satmap(True)
            self.reset_control_scheme(['vehicle','vehicle'])
            self.worldmap_task.active_agents = [0,1]
            self.create_invaders(self.invader_count)
            self.create_controllables()

            # display the truck icon on satmap
            visible_to = [0,1]
            self.truck_gizmo = SmartGizmo(
                display_scenegraphs=[self.clients[j].city for j in visible_to] + [self.city],
                display_funcs=[(self.clients[j].conn.modules.framework.ui_elements.WorldspaceGizmos.create_worldspace_gizmo,self.clients[j].conn.modules.framework.ui_elements.WorldspaceGizmos.destroy_worldspace_gizmo) for j in visible_to] + [(create_worldspace_gizmo,destroy_worldspace_gizmo)],
                display_engines=[self.clients[j]._engine for j in visible_to] + [self._engine],
                client_indices = visible_to + [2],
                pos=self.truck_pos,image=self.truck_icon,scale=self.agent_icon_scale,opacity=0.95,oncamera=False,onsatmap=True,onexperimenter=True,billboard=True,throughwalls=True)

            # show instructions
            self.broadcast_message('starting now, perform the secure-the-perimeter mission with your partner.',mission=True)
            self.sleep(5)
            # set up periodic score update
            taskMgr.doMethodLater(self.secureperimeter_score_gain_period,self.update_score_periodic,'UpdateScorePeriodic',extraArgs=[self.secureperimeter_score_gain,[0,1]], appendTask=True)
            # run for a randomly predetermined time
            duration = random.uniform(self.secure_perimeter_duration[0],self.secure_perimeter_duration[1])
            tEnd = time.time() + duration            
            while time.time() < tEnd:
                # check conditions for each invader         
                for a in self.invaders:
                    if a.mode == "hiding":
                        continue

                    # check if any invader has line-of-sight with the truck
                    a_pos = Point3(a.pos.getX(),a.pos.getY(),a.pos.getZ()+self.hostile_agent_head_height)
                    if line_of_sight(self.physics, a_pos, self.truck_pos, a.vel, src_fov=self.hostile_field_of_view) is not None:
                        self.marker('Experiment Control/Task/Hint/Truck Was Spotted')
                        self.broadcast_message('the truck is in a dangerous situation!')
                        self.update_score_both(self.danger_penalty)
                        self.sleep(3)

                    # check if any invader is spotted by a friendly agent
                    for k in range(len(self.agents)):
                        v = self.agents[k]
                        viewdir = v.getParent().getMat(self.city).getRow(1)
                        los = line_of_sight(self.physics,v.getPos(self.city),
                            a_pos,Vec3(viewdir.getX(),viewdir.getY(),viewdir.getZ()),
                            a.vel,src_fov=self.friendly_field_of_view,dst_fov=self.hostile_field_of_view,src_maxsight=self.fendoff_distance)
                        if los is not None:
                            if los == "front" and (not a.mode == "retreating"):
                                self.clients[k].viewport_instructions.submit(self.clients[k].id + ', you have fended off an intruder!')
                                self.clients[1-k].viewport_instructions.submit(self.clients[1-k].id + ', your partner has fended off an intruder!')
                                a.enter_retreat(v.getPos(self.city))
                                self.update_score_both(self.chaseaway_bonus)
                                self.sleep(1)

                    # check if any invader is spotted by a voice-controllable robot
                    for v in self.controllables:
                        viewdir = v.vel
                        los = line_of_sight(self.physics,
                            v.pos,a_pos,Vec3(viewdir.getX(),viewdir.getY(),viewdir.getZ()),
                            a.vel,src_fov=self.friendly_field_of_view,dst_fov=self.hostile_field_of_view,src_maxsight=self.controllables_max_sight)
                        if los is not None:
                            if los == "front" and (not a.mode == "retreating"):
                                self.broadcast_message('one of your guards has fended off an intruder!')
                                a.enter_retreat(v.getPos(self.city))
                                self.update_score_both(self.chaseaway_bonus)
                                self.sleep(1)

                    # check if any friendly agent is spotted from behind by an enemy
                    for v in self.agents:
                        if line_of_sight(self.physics,
                            a_pos,v.getPos(self.city),a.vel,Vec3(viewdir.getX(),viewdir.getY(),viewdir.getZ()),
                            src_fov=self.hostile_field_of_view,dst_fov=self.friendly_field_of_view) == "behind":
                            self.marker('Experiment Control/Task/Hint/Spotted From Behind')
                            self.clients[k].viewport_instructions.submit(self.clients[k].id + ', your robot was spotted from behind!')
                            self.clients[1-k].viewport_instructions.submit(self.clients[1-k].id + ', your partner''s robot was spotted from behind!')
                            self.update_score_both(self.unfortunate_spotting_penalty)
                            self.sleep(3)

                # update policy shortly
                self.sleep(0.25)

            self.update_score_both(self.perimeter_finish_bonus)
        finally:
            # clean up
            if self.truck_gizmo:
                self.truck_gizmo.destroy()
            self.destroy_controllables()
            self.destroy_invaders()
            taskMgr.remove('UpdateScorePeriodic')

    @livecoding
    def play_lulldeep(self):
        """
        A mission in which both subjects rest for X minutes and have nothing to do but watch the warning lightr.
        """
        try:
            for cl in self.clients:
                cl.toggle_satmap(True)
                cl.attention_manager.mask_regions([])
                cl.stress_task.disabled = True
            self.reset_control_scheme(['static','static'])
            self.worldmap_task.active_agents = []
            self.broadcast_message('starting now, do nothing except watch and respond to the red warning light for the next few minutes.',mission=True)
            self.sleep(5)
            self.sleep(random.uniform(self.lull_duration[0],self.lull_duration[1]))
        finally:
            for cl in self.clients:
                cl.attention_manager.mask_regions(self.available_attention_set)
                cl.stress_task.disabled = False

    @livecoding
    def play_freeroam(self):
        """
        A testing mission that allows the subjects to roam freely.
        """
        for cl in self.clients:
            cl.toggle_satmap(True)
        self.reset_control_scheme(['vehicle','vehicle'])
        self.worldmap_task.active_agents = []
        self.broadcast_message('starting now, you may roam freely.',mission=True)
        self.sleep(10000)

    # ====================
    # === PHYSICS CODE ===
    # ====================

    @livecoding
    def init_physics(self):
        """ Initialize physics simulation. """
        self.meshes = []
        self.shapes = []        
        # create physics simulation
        self.physics = BulletWorld()
        self.physics.setGravity(Vec3(0, 0, -self.gravity))
        # add vehicles
        for k in range(len(self.agents)):
            self.vehicles.append(self.init_physics_vehicle(self.agents[k],k))            
        # add collision geometry
        self.init_physics_city()
        self.init_physics_terrain()        
        # start
        self.physics_lasttime = None
        self.last_reset_time = [0,0]
        self.start_physics()

    @livecoding
    def init_physics_city(self):
        """ Generate city collision detection. """
        if self.city is not None:
            print "Generating collision info for city...",
            for gnp in self.city.findAllMatches('**/-GeomNode'):
                geomnode = gnp.node()
                for k in range(geomnode.getNumGeoms()):
                    geom = geomnode.getGeom(k)
                    mesh = BulletTriangleMesh()
                    mesh.addGeom(geom)
                    shape = BulletTriangleMeshShape(mesh, dynamic=False)
                    np = self.world_root.attachNewNode(BulletRigidBodyNode(geomnode.getName() + '-' + str(k)))
                    np.node().addShape(shape)
                    np.setPos(gnp.getPos(render))
                    np.setScale(gnp.getScale(render))
                    np.setHpr(gnp.getHpr(render))
                    np.setCollideMask(BitMask32.allOn())
                    self.physics.attachRigidBody(np.node())
                    self.meshes.append(mesh)
                    self.shapes.append(shape)
            print "done."

    @livecoding
    def init_physics_terrain(self):
        """ Generate terrain collision detection. """
        if self.terrain is not None:
            print "Generating collision info for terrain...",
            shape = BulletHeightfieldShape(PNMImage(self.terrain_heightmap),self.terrainheight,ZUp)
            np = self.world_root.attachNewNode(BulletRigidBodyNode("Terrain"))
            np.node().addShape(shape)
            np.setPos(0.0,0.0,self.terrainheight/2.0 + self.terrain_offset + self.terrain_collision_offset)
            np.setScale(self.terrain_rescale[0]*self.terrainsize/1025.0,self.terrain_rescale[1]*self.terrainsize/1025.0,1.0)
            np.setCollideMask(BitMask32.allOn())
            self.physics.attachRigidBody(np.node())
            print "done."        

    @livecoding
    def init_physics_vehicle(self,sourcenode,k):
        """ Init a player-controlled vehicle. """
        print "Setting up player-controlled vehicle...",        
        # add chassis, using the transform of the agent vehicle
        chassisshape = BulletBoxShape(Vec3(self.vehicle_chassis_size[0], self.vehicle_chassis_size[1], self.vehicle_chassis_size[2]))                
        ts = TransformState.makePos(Point3(self.vehicle_chassis_offset[0], self.vehicle_chassis_offset[1], self.vehicle_chassis_offset[2]))
        chassisnp = self.world_root.attachNewNode(BulletRigidBodyNode('Vehicle'+str(k)))
        chassisnp.setPos(sourcenode.getPos(self.city))
        chassisnp.setH(sourcenode.getH(chassisnp))
        chassisnp.node().addShape(chassisshape,ts)
        chassisnp.node().setMass(self.vehicle_mass)
        chassisnp.node().setDeactivationEnabled(False)
        self.physics.attachRigidBody(chassisnp.node())
        # add vehicle model
        vehicle = BulletVehicle(self.physics, chassisnp.node())
        self.physics.attachVehicle(vehicle)
        # add wheels to vehicle
        self.init_physics_wheel(vehicle, Point3( self.vehicle_wheel_lateral_offset,  self.vehicle_wheel_longitudinal_offset, self.vehicle_wheel_vertical_offset), True)
        self.init_physics_wheel(vehicle, Point3(-self.vehicle_wheel_lateral_offset,  self.vehicle_wheel_longitudinal_offset, self.vehicle_wheel_vertical_offset), True)
        self.init_physics_wheel(vehicle, Point3( self.vehicle_wheel_lateral_offset, -self.vehicle_wheel_longitudinal_offset, self.vehicle_wheel_vertical_offset), False)
        self.init_physics_wheel(vehicle, Point3(-self.vehicle_wheel_lateral_offset, -self.vehicle_wheel_longitudinal_offset, self.vehicle_wheel_vertical_offset), False)
        # attach the renderable vehicle geometry to the physical vehicle chassis, moved up a bit (since the chassis is too high)
        sourcenode.reparentTo(chassisnp)
        sourcenode.setPosHpr(self.vehicle_geometry_offset[0],self.vehicle_geometry_offset[1],self.vehicle_geometry_offset[2],0,-90,0)
        print "done."
        return vehicle

    @livecoding
    def init_physics_wheel(self,vehicle,pos,isfront):
        """ Init a single wheel of a player-controlled vehicle. """
        wheel = vehicle.createWheel()
        wheel.setChassisConnectionPointCs(pos)
        wheel.setFrontWheel(isfront)    
        wheel.setWheelDirectionCs(Vec3(0, 0, -1))
        wheel.setWheelAxleCs(Vec3(1, 0, 0))
        wheel.setWheelRadius(self.vehicle_wheel_radius)
        wheel.setMaxSuspensionTravelCm(self.vehicle_suspension_travel_cm)    
        wheel.setSuspensionStiffness(self.vehicle_suspension_stiffness)
        wheel.setWheelsDampingRelaxation(self.vehicle_wheel_damping_relaxation)
        wheel.setWheelsDampingCompression(self.vehicle_wheel_damping_compression)
        wheel.setFrictionSlip(self.vehicle_friction_slip)
        wheel.setRollInfluence(self.vehicle_wheel_roll_influence)

    @livecoding
    def start_physics(self):
        taskMgr.add(self.update_physics,"UpdatePhysics")
        # allow the players to reset their vehicles (if they broke down or the like)
        self.accept('r-cl0-down',lambda: self.on_client_reset_vehicle(0))
        self.accept('r-cl1-down',lambda: self.on_client_reset_vehicle(1))

    #noinspection PyUnusedLocal
    @livecoding
    def update_physics(self,task):
        """Update the physics simulation."""
        now = time.time()
        if self.physics_lasttime is None:
            self.physics_lasttime = now
        dt = now - self.physics_lasttime
        self.physics_lasttime = now

        # get the controller inputs
        for client in [0,1]:
            x = self.clients[client].axis_x
            y = self.clients[client].axis_y
            u = self.clients[client].axis_u
            v = self.clients[client].axis_v

            brake = self.clients[client].braking
            handbrake = self.clients[client].handbrake_engaged or self.clients[client].is_locked_down()
            if self.agent_control[client] == 'vehicle':
                # apply vehicular steering
                cur_speed = self.vehicles[client].getCurrentSpeedKmHour()
                steering = max(0,abs(y)-self.vehicle_dead_zone) * (-1 if y<0 else +1)
                self.vehicles[client].setSteeringValue(-steering*self.steering_range * self.steering_dampspeed/(self.steering_dampspeed+cur_speed), 0)
                self.vehicles[client].setSteeringValue(-steering*self.steering_range * self.steering_dampspeed/(self.steering_dampspeed+cur_speed), 1)
                engine_force = self.engine_force
                if x > 0 and cur_speed > 0:
                    engine_force *= self.reverse_brake_force_multiplier
                if cur_speed > self.vehicle_upper_speed:
                    engine_force *= max(0,(1 - (cur_speed - self.vehicle_upper_speed) / (self.vehicle_top_speed - self.vehicle_upper_speed)))
                self.vehicles[client].applyEngineForce(engine_force*-x, 2)
                self.vehicles[client].applyEngineForce(engine_force*-x, 3)
                if brake or handbrake:
                    self.vehicles[client].setBrake(self.brake_force, 0)
                    self.vehicles[client].setBrake(self.brake_force, 1)
                else:
                    self.vehicles[client].setBrake(self.vehicle_roll_friction, 0)
                    self.vehicles[client].setBrake(self.vehicle_roll_friction, 1)
            elif self.agent_control[client] == 'aerial':
                # apply aerial steering
                if not self.clients[client].is_locked_down():
                    ch = self.vehicles[client].getChassis()
                    mat = self.agents[client].getParent().getMat(render)
                    left = -mat.getRow3(0)
                    forward = mat.getRow3(1)
                    forward.setZ(0)
                    forward *= 1.0 / forward.length()
                    ch.applyCentralForce(Vec3(left.getX()*-y*self.aerial_accel,left.getY()*-y*self.aerial_accel,left.getZ()*-y*self.aerial_accel))
                    ch.applyCentralForce(Vec3(forward.getX()*-x*self.aerial_accel,forward.getY()*-x*self.aerial_accel,forward.getZ()*-x*self.aerial_accel))
                    ch.applyTorque(Vec3(0,0,-v*self.aerial_turnrate))
                    ch.applyTorque(Vec3(left.getX()*u*self.aerial_turnrate,left.getY()*u*self.aerial_turnrate,left.getZ()*u*self.aerial_turnrate))
            elif self.agent_control[client] == 'static':
                # engage brakes and disable steering
                self.vehicles[client].applyEngineForce(0, 2)
                self.vehicles[client].applyEngineForce(0, 3)
                self.vehicles[client].setSteeringValue(0, 0)
                self.vehicles[client].setSteeringValue(0, 1)
                self.vehicles[client].setBrake(self.brake_force, 0)
                self.vehicles[client].setBrake(self.brake_force, 1)
            elif self.agent_control[client] == 'panning':
                # engage brakes and disable steering
                self.vehicles[client].applyEngineForce(0, 2)
                self.vehicles[client].applyEngineForce(0, 3)
                self.vehicles[client].setSteeringValue(0, 0)
                self.vehicles[client].setSteeringValue(0, 1)
                self.vehicles[client].setBrake(self.brake_force, 0)
                self.vehicles[client].setBrake(self.brake_force, 1)
                # add pan control
                if not self.clients[client].is_locked_down():
                    mat = self.agents[client].getParent().getMat(render)
                    row3 = mat.getRow(3)
                    steering = max(0,abs(y)-self.panning_dead_zone) * (-1 if y<0 else +1)
                    mat *= Mat4.rotateMat(-steering*self.pan_speed,mat.getRow3(2))
                    mat.setRow(3,row3)
                    self.agents[client].getParent().setMat(render,mat)

        # extra aerial control logic (fly-by-wire)
        if 'aerial' in self.agent_control:
            aerial_idx = self.agent_control.index('aerial')
            p = self.agents[aerial_idx].getPos(render)
            # speed damping
            self.vehicles[aerial_idx].getChassis().setAngularDamping(self.aerial_angular_damping)
            self.vehicles[aerial_idx].getChassis().setLinearDamping(self.aerial_linear_damping)
            # updrift
            self.vehicles[aerial_idx].getChassis().applyCentralImpulse(Vec3(0, 0, self.rise_force_offset + self.rise_force*max(0,(self.rise_altitude-p.getZ()))))
            # axis stabilization
            left = self.agents[aerial_idx].getParent().getMat(render).getRow3(0)
            left_planar = self.agents[aerial_idx].getParent().getMat(render).getRow3(0)
            left_planar.setZ(0)
            left_planar *= 1.0 / left_planar.length()
            correction = left.cross(left_planar) * self.axis_stabilization
            #noinspection PyUnresolvedReferences
            self.vehicles[aerial_idx].getChassis().applyTorque(Vec3(correction.getX(),correction.getY(),correction.getZ()))

        self.physics.doPhysics(dt, self.physics_solver_max_substeps, self.physics_solver_stepsize)
        self.vehicles[0].getChassis().clearForces()
        self.vehicles[1].getChassis().clearForces()
        return Task.cont


    # =================================
    # === AI-CONTROLLED AGENT LOGIC ===    
    # =================================

    @livecoding
    def create_wanderers(self,num=10,box_constraint=None):
        self.wanderers = []
        for n in range(num):
            self.wanderers.append(WanderingAgent(
                crowd=self.navcrowd,
                physics=self.physics,
                surfacegraph=self.city,
                scene_graphs=[self.clients[0].city,self.clients[1].city,self.city],
                engines=[self.clients[0]._engine,self.clients[1]._engine,self._engine],
                models=[self.clients[0].hostile_model,self.clients[1].hostile_model,self.hostile_model],
                spawn_pos=None,
                wander=True,
                line_of_sight=False,
                box_constraint=box_constraint))
        taskMgr.add(self.update_wanderers,"UpdateWanderers")

    @livecoding
    def update_wanderers(self,task):
        for a in self.wanderers:
            a.update()
        self.update_lsl_agentstate()
        if len(self.wanderers) > 0:
            return task.cont

    @livecoding
    def destroy_wanderers(self):
        for a in self.wanderers:
            del a
        self.wanderers = []

    @livecoding
    def create_invaders(self,num=6):
        pos = self.truck_pos
        delta = num-len(self.invaders)
        for n in range(delta):
            self.invaders.append(InvadingAgent(
                crowd=self.navcrowd,
                scene_graphs=[self.clients[0].city,self.clients[1].city,self.city],
                engines=[self.clients[0]._engine,self.clients[1]._engine,self._engine],
                models=[self.clients[0].hostile_model,self.clients[1].hostile_model,self.hostile_model],
                bulletworld=self.physics,
                spawn_pos=pos,
                hotspot=pos,
                jitter=self.agent_scatter))
        if delta == num: 
            taskMgr.add(self.update_invaders,"UpdateInvaders")

    @livecoding
    def update_invaders(self,task):
        for a in self.invaders:
            a.update()
        self.update_lsl_agentstate()
        if len(self.invaders)>0:
            return task.cont

    @livecoding
    def destroy_invaders(self):
        for a in self.invaders:
            del a
        self.invaders = []

    @livecoding
    def create_controllables(self):
        if len(self.controllables) == 0:
            pos = self.truck_pos
            for n in range(len(self.controllable_ids)):
                self.controllables.append(WanderingAgent(
                    crowd=self.navcrowd,
                    physics=self.physics,
                    surfacegraph=self.city,
                    scene_graphs=[self.clients[0].city,self.clients[1].city,self.city],
                    engines=[self.clients[0]._engine,self.clients[1]._engine,self._engine],
                    models=[self.clients[0].friendly_model,self.clients[1].friendly_model,self.friendly_model],
                    spawn_pos=pos,
                    spawn_radius_max=self.controllable_scatter,
                    spawn_radius_min=self.controllable_min_spawndistance,
                    wander=False))
            taskMgr.add(self.update_controllables,"UpdateControllables")

    @livecoding
    def update_controllables(self,task):
        for a in self.controllables:
            a.update()
        self.update_lsl_agentstate()
        if len(self.controllables)>0:
            return task.cont

    @livecoding
    def destroy_controllables(self):
        for a in self.controllables:
            del a
        self.controllables = []


    # =================================
    # === REMOTE GAME-STATE UPDATES ===
    # =================================

    @livecoding
    def update_score_periodic(self,delta,client_ids,task):
        """ Periodically update the score for a subset of clients by a given delta. """
        for c in client_ids:
            self.clients[c].overall_score.score_event(delta*self.clients[c].stress_task.stress_level,nosound=True)
        return task.again

    @livecoding
    def update_score_both(self,delta):
        """ Update the score of both clients. """
        for cl in self.clients:
            cl.overall_score.score_event(delta*cl.stress_task.stress_level)

    @livecoding
    def broadcast_message(self,msg,no_callsign=False,mission=False,client=None):
        """ Send a text message to one or both clients. Optionally also present on the mission text screen."""
        self.message_presenter.submit(msg)
        if client is None:
            for cl in self.clients:
                cl.viewport_instructions.submit(('' if no_callsign else cl.id + ', ') + msg)
                if mission:
                    cl.mission_text.submit(('' if no_callsign else cl.id + ', ') + msg)
        else:
            self.clients[client].viewport_instructions.submit(('' if no_callsign else self.clients[client].id + ', ') + msg)
            if mission:
                self.clients[client].mission_text.submit(('' if no_callsign else self.clients[client].id + ', ') + msg)

        self.marker('Stimulus/Visual/Language/Sentence/%s, Participant/ID/both' % msg)

    @livecoding
    def broadcast_agentstate(self):
        """Update the observable state of the agents on the client machines."""
        for k in range(len(self.agents)):
            pos = self.agents[k].getPos(render)
            hpr = self.agents[k].getHpr(render)
            for cl in self.clients:
                cl.update_agents_poshpr[k](pos.x,pos.y,pos.z,hpr.x,hpr.y,hpr.z)
        self.update_lsl_playerstate()


    #noinspection PyUnusedLocal
    @livecoding
    def broadcast_gamestate(self,task):
        """Update the entire dynamic observable gamestate on the client machines."""
        self.broadcast_agentstate()
        return Task.cont    

    @livecoding
    def update_terrain(self,task):
        for cl in self.clients:
            cl.update_terrain()
        return task.cont

    # ============================================
    # === EXPERIMENTER CAMERA CONTROL HANDLERS ===
    # ============================================

    #noinspection PyUnusedLocal
    @livecoding
    def on_camtick(self,task):
        """Update experimenter' camera position."""
        now = time.time()
        dt = now - self.cam_lasttime
        self.cam_lasttime = now
        self.cam_position += self.cam_velocity * dt
        self.cam_orientation += self.cam_angular_velocity * dt
        self.cam_velocity *= pow(self.cam_friction,dt)
        self.cam_angular_velocity *= pow(self.cam_angular_friction,dt)
        self.camera.setPos(self.cam_position)
        self.camera.setHpr(self.cam_orientation)
        return Task.cont

    def on_forward(self):
        forward = self.camera.getMat().getRow3(1)
        self.cam_velocity += forward*self.cam_acceleration

    def on_reverse(self):
        reverse = -self.camera.getMat().getRow3(1)
        self.cam_velocity += reverse*self.cam_acceleration

    def on_left(self):
        left = -self.camera.getMat().getRow3(0)
        self.cam_velocity += left*self.cam_acceleration

    def on_right(self):
        right = self.camera.getMat().getRow3(0)
        self.cam_velocity += right*self.cam_acceleration

    def on_up(self):
        planar_forward = self.camera.getMat().getRow3(1)
        planar_forward.setZ(0)
        planar_forward *= 1.0 / planar_forward.length()
        self.cam_velocity += planar_forward*self.cam_acceleration

    def on_down(self):
        planar_reverse = -self.camera.getMat().getRow3(1)
        planar_reverse.setZ(0)
        planar_reverse *= 1.0 / planar_reverse.length()
        self.cam_velocity += planar_reverse*self.cam_acceleration

    def on_turnleft(self):
        self.cam_angular_velocity += Point3(self.cam_turnrate,0,0)

    def on_turnright(self):
        self.cam_angular_velocity -= Point3(self.cam_turnrate,0,0)

    def on_turnup(self):
        self.cam_angular_velocity += Point3(0,self.cam_turnrate,0)

    def on_turndown(self):
        self.cam_angular_velocity -= Point3(0,self.cam_turnrate,0)


    # =============================
    # === CLIENT EVENT HANDLERS ===
    # =============================

    #noinspection PyUnusedLocal
    @livecoding
    def on_joystick(self,client,x,y,u,v,buttons):
        """ Handle joystick events. """
        if buttons[0]:   # Gamepad A button
            if self.agent_control[client] == 'panning':
                self.on_client_report(client)
            else:
                self.on_client_warn(client)
        if buttons[1]:   # Gamepad B button
            self.on_client_reset_vehicle(client)

    @livecoding
    def on_pushtotalk(self,client):
        rpyc.async(self.clients[client].remote_stimpresenter.sound)(self.pushtotalk_sound,volume=self.pushtotalk_own_volume,block=False)
        rpyc.async(self.clients[1-client].remote_stimpresenter.sound)(self.pushtotalk_sound,volume=self.pushtotalk_other_volume,block=False)

    @livecoding
    def on_client_report(self,c):
        """ Called when a client preses the 'report' button during the pan-the-cam mission. """
        now = time.time()
        if now - self.last_report_press_time[c] > self.report_repeat_press_interval:
            report_valid = False
            # get all agents in direct field of view
            v = self.agents[c]
            v_pos = v.getPos(self.city)
            v_vec = v.getParent().getMat(self.city).getRow3(1)
            v_vec = Vec3(v_vec.getX(),v_vec.getY(),v_vec.getZ())
            # for each agent...
            score_delta = 0
            for a in self.wanderers:
                a_pos = Point3(a.pos.getX(),a.pos.getY(),a.pos.getZ()+self.hostile_agent_head_height)
                counts_as_report = line_of_sight(self.physics, v_pos, a_pos, v_vec, a.vel, src_fov=self.report_field_of_view,src_maxsight=self.pancam_max_report_distance) is not None
                if counts_as_report:
                    a.on_reported()
                    report_valid = True
                    # last report was long enough ago or the object had not been potentially visible since some time after the last report
                    if now - a.last_report_time[c] > self.double_report_cutoff or a.last_report_time[c] < a.potentially_invisible_since[c]:
                        # valid report
                        self.marker('Experiment Control/Task/Action/Correct, Experiment Control/Task/PanTheCam/Reported Object/{identifier:%i}, Participants/ID/%i' % (a.identifier,c))
                        score_delta += self.pancam_spotted_gain
                    else:
                        # reporting the same object in too short succession
                        self.marker('Experiment Control/Task/Action/Incorrect, Experiment Control/Task/PanTheCam/Doubly Reported Object/{identifier:%i}, Participants/ID/%i' % (a.identifier,c))
                        score_delta += self.pancam_double_loss
                    a.last_report_time[c] = now
            if report_valid:
                self.clients[c].overall_score.score_event(score_delta,nosound=False)
            else:
                self.marker('Experiment Control/Task/Action/Incorrect, Experiment Control/Task/PanTheCam/False Report, Participants/ID/%i' % c)
                self.clients[c].overall_score.score_event(self.pancam_false_loss,nosound=False)
            self.last_report_press_time[c] = now

    def client_ack(self):
        """ callback when a client has acknowledged something (only during game startup). """
        self.num_acks += 1

    @livecoding
    def on_client_warn(self,idx):
        """ Callback when a client has pressed the "warn off" button. """ 
        self.marker('Response/Button Press/Warn Agents')
        v = self.agents[idx]
        rpyc.async(self.clients[idx].remote_stimpresenter.sound)(self.alert_sound,block=False)
        viewdir = v.getParent().getMat(self.city).getRow(1)
        num_warnedoff = 0
        num_alreadyretreating = 0
        for a in self.invaders:
            if a.mode == "hiding":
                continue
            # check if any invader has line-of-sight with the responsible player
            a_pos = Point3(a.pos.getX(),a.pos.getY(),a.pos.getZ()+self.hostile_agent_head_height)
            los = line_of_sight(self.physics,v.getPos(self.city),a_pos,Vec3(viewdir.getX(),viewdir.getY(),viewdir.getZ()),a.vel,src_fov=self.friendly_field_of_view,dst_fov=self.hostile_field_of_view,src_maxsight=self.warn_distance)
            if los is not None:
                if a.mode == "retreating":
                    num_alreadyretreating += 1
                else:
                    num_warnedoff += 1
                    self.marker('Stimulus/Feedback/Reward/On Accuracy')
                    a.enter_retreat(v.getPos(self.city))
                    self.update_score_both(self.threatenaway_bonus)
        if num_warnedoff > 0:
            self.clients[idx].viewport_instructions.submit(self.clients[idx].id + ', you have successfully warned off an agent!')
        elif num_alreadyretreating > 0:
            # note: this message is only issued when there's not already at least one agent who was successfully warned off
            self.clients[idx].viewport_instructions.submit('This agent is already retreating.')
        else:
            self.clients[idx].viewport_instructions.submit('There is no agent.')

    @livecoding
    def on_client_speech(self,
                         cl_idx,               # index of the participant emitting the speech
                         phrase,               # the raw phrase that was emitted
                         actual_speech=True    # whether the modality is in fact speech or rather a press of a labeled button
                         ):
        """ Handles the subjects' speech responses. """

        print str(time.time()) + " client",cl_idx,"said:",phrase
        if actual_speech:
            if not self.clients[cl_idx].push_to_talk:
                print str(time.time()) + ": ignoring speech detection due to push-to-talk not being pressed (",phrase,")"
                self.marker('Experiment Control/Task/IgnoredResponse/Speech/%s, Participant/ID/%i' % (phrase,cl_idx))
                return
            self.marker('Response/Speech/%s, Participant/ID/%i' % (phrase,cl_idx))
        else:
            self.marker('Response/Button Press/Touch Screen/%s, Participant/ID/%i' % (phrase,cl_idx))

        tokens = phrase.split(' ')
        if len(tokens) == 1:
            # single-word responses are directly translated into a message of the form 'cl0-word'
            message = 'cl' + str(cl_idx) + '-' + tokens[0].lower().strip()
            print str(time.time()) + " generating message " + message
            self.send_message(message)

            # ensure that the response modality is alternated at a reasonable rate
            if self.last_modality == actual_speech:
                self.same_modality_repeats += 1
                if self.same_modality_repeats > self.max_same_modality_responses:
                    self.clients[cl_idx].remote_stimpresenter.sound(self.repeated_response_penalty_sound,volume=self.repeated_response_penalty_volume)
                    self.clients[cl_idx].overall_score.score_event(self.repeated_response_loss,nosound=True)
            else:
                self.same_modality_repeats = 0
                self.last_modality = actual_speech

        elif phrase.strip() == 'suspicious object':
            # special handling for the "suspicious object" utterance
            message = 'cl' + str(cl_idx) + '-report'
            print str(time.time()) + " generating message " + message
            self.send_message(message)

        # handle commands addressed at named entities/robots (the so-called controllables)
        cids = [x.lower() for x in self.controllable_ids]
        if tokens[0].lower() in cids:
            ag_idx = cids.index(tokens[0].lower())
            if len(self.controllables)<=ag_idx:
                return
            ag = self.controllables[ag_idx]
            cl = self.agents[cl_idx]
            if tokens[1] == "move":
                if tokens[2] == "here":
                    ag.move_to_location(cl.getPos(self.city))
                elif tokens[2:6] == ["in","front","of","me"]:
                    pos = cl.getPos(self.city)
                    front = cl.getParent().getMat(self.city).getRow(1)
                    ag.move_to_location(pos + Vec3(front.getX(),front.getY(),front.getZ()) * self.relative_move_distance)
                elif tokens[2:4] == ["behind","me"]:
                    pos = cl.getPos(self.city)
                    front = cl.getParent().getMat(self.city).getRow(1)
                    ag.move_to_location(pos - Vec3(front.getX(),front.getY(),front.getZ()) * self.relative_move_distance)
                elif tokens[2:5] == ["to","my","left"]:
                    pos = cl.getPos(self.city)
                    front = cl.getParent().getMat(self.city).getRow(0)
                    ag.move_to_location(pos - Vec3(front.getX(),front.getY(),front.getZ()) * self.relative_move_distance)
                elif tokens[2:5] == ["to","my","right"]:
                    pos = cl.getPos(self.city)
                    front = cl.getParent().getMat(self.city).getRow(0)
                    ag.move_to_location(pos + Vec3(front.getX(),front.getY(),front.getZ()) * self.relative_move_distance)
                elif tokens[2:4] == ["to","truck"]:
                    ag.move_to_location(self.truck_pos)

    @livecoding
    def on_client_reset_vehicle(self,
                                num        # index client of the client requesting the reset
                                ):
        """ Reset a lost player vehicle: places it on the map again and resets the orientation. """
        # reset can only be triggered once every few seconds
        if time.time() > (self.last_reset_time[num] + self.min_reset_interval) and self.agent_control[num] == 'vehicle':
            print "Client " + str(num) + " pressed the reset button."
            self.marker('Response/Button Press/Reset Vehicle, Participant/ID/%i' % num)
            #noinspection PyUnresolvedReferences
            framework.tickmodule.shared_lock.acquire()
            # stop vehicle
            self.vehicles[num].getChassis().setLinearVelocity(Vec3(0,0,0))
            self.vehicles[num].getChassis().setAngularVelocity(Vec3(0,0,0))

            # find a nearby point on the navmesh to reset to
            oldpos = self.agents[num].getParent().getPos(self.city)
            if (time.time() - self.last_reset_time[num]) < self.repeat_reset_interval:
                oldpos.setX(oldpos.getX()+random.uniform(-self.repeat_reset_jitter,self.repeat_reset_jitter))
                oldpos.setY(oldpos.getY()+random.uniform(-self.repeat_reset_jitter,self.repeat_reset_jitter))
            meshpos = navigation.detour2panda(self.navmesh.nearest_point(pos=oldpos, radius=self.reset_snap_radius)[1])
            # raycast upwards to find the height of the world (in case this is within a building we'll spawn on the roof) and correct position
            hittest = self.physics.rayTestAll(meshpos,Point3(meshpos.getX(),meshpos.getY(),meshpos.getZ()+self.reset_snap_radius))
            if hittest.getNumHits() > 0:
                max_fraction = max([hittest.getHit(k).getHitFraction() for k in range(hittest.getNumHits())])
                meshpos.setZ(meshpos.getZ() + max_fraction*self.reset_snap_radius)
            self.agents[num].getParent().setPos(self.city,meshpos.getX(),meshpos.getY(),meshpos.getZ()+self.reset_height)
            # fix up the rotation matrix
            mat = self.agents[num].getParent().getMat(render)
            rescale = mat.getRow3(2).length()
            on_roof = mat.getRow3(2).getZ() < 0
            vforward = -mat.getRow3(1) if on_roof else mat.getRow3(1)
            vforward.setZ(0)
            vforward *= rescale / vforward.length()
            vup = Vec3(0,0,rescale)
            vright = -vup.cross(vforward)
            vright *= rescale / vright.length()
            mat.setRow(0,vright)
            mat.setRow(1,vforward)
            mat.setRow(2,vup)
            self.agents[num].getParent().setMat(render,mat)
            self.last_reset_time[num] = time.time()
            #noinspection PyUnresolvedReferences
            framework.tickmodule.shared_lock.release()
            try:
                self.clients[num].overall_score.score_event(self.reset_penalty)
            except:
                # score counter is only set up while the actual tasks are running
                pass


    # ==========================
    # === GAME LOGIC HELPERS ===
    # ==========================

    @livecoding
    def reset_control_scheme(self,
                             schemelist,            # a list of control schemes, e.g. ['vehicle','static']
                             randomize=True):       # whether to randomize the list order
        """ Reset the control scheme for the two clients. """
        if randomize and random.random() < 0.5:
            schemelist.reverse()
        self.agent_control = schemelist
        for i in range(len(schemelist)):
            self.marker('Experiment Control/Task/Control Scheme/Reset/%s, Participant/ID/%i' % (schemelist[i],i))

        self.vehicle_idx = self.agent_control.index('vehicle') if 'vehicle' in self.agent_control else None
        self.aerial_idx = self.agent_control.index('aerial') if 'aerial' in self.agent_control else None
        self.static_idx = self.agent_control.index('static') if 'static' in self.agent_control else None
        self.panning_idx = self.agent_control.index('panning') if 'panning' in self.agent_control else None

    @livecoding
    def create_checkpoint(self,
                          visible_to,   # indices of the clients who should be able to see the checkpoint
                          **kwargs):
        """Helper function to create a new checkpoint gizmo object with the correct display parameters set up. """
        return SmartGizmo(
            display_scenegraphs=[self.clients[k].city for k in visible_to] + [self.city],
            display_funcs=[(self.clients[k].conn.modules.framework.ui_elements.WorldspaceGizmos.create_worldspace_gizmo,self.clients[k].conn.modules.framework.ui_elements.WorldspaceGizmos.destroy_worldspace_gizmo) for k in visible_to] + [(create_worldspace_gizmo,destroy_worldspace_gizmo)],
            display_engines=[self.clients[k]._engine for k in visible_to] + [self._engine],
            client_indices = visible_to + [2],
            gizmo_name='Checkpoint',
            cam_scale=self.checkpoint_scale_cam,
            sat_scale=self.checkpoint_scale_satmap,
            **kwargs)


    # ================
    # === LSL CODE ===
    # ================

    @livecoding
    def init_lsl_playerstream(self):
        """ Initialize the PlayerCoordinates stream for LSL. """
        info = pylsl.stream_info('SNAP-LSE-PlayerCoordinates','Control',(3+3)*2,0,pylsl.cf_float32,'SNAP-LSE-Playerstream' + server_version + str(self.permutation))
        # append some serious meta-data
        channels = info.desc().append_child('channels')
        for agent in [0,1]:
            agent_name = 'Player' + str(agent)
            for coord in ['X','Y','Z']: 
                chn = channels.append_child('channel')
                chn.append_child_value('name',agent_name + 'Position' + coord)
                chn.append_child_value('type','Position' + coord)
                chn.append_child_value('unit','meters')
                chn.append_child_value('object',agent_name)
            for axis in ['H','P','R']:
                chn = channels.append_child('channel')
                chn.append_child_value('name',agent_name + 'Orientation' + axis)
                chn.append_child_value('type','Orientation' + axis)
                chn.append_child_value('unit','degrees')
                chn.append_child_value('object',agent_name)
        self.player_positions_outlet = pylsl.stream_outlet(info)

    @livecoding        
    def update_lsl_playerstate(self):
        """ Push a new sample into the PlayerCoordinates stream. """
        mysample = []
        for k in range(len(self.agents)):
            pos = self.agents[k].getPos(render)
            hpr = self.agents[k].getHpr(render)
            mysample += [pos.getX(),pos.getY(),pos.getZ(),hpr.getX(),hpr.getY(),hpr.getZ()]
        self.player_positions_outlet.push_sample(pylsl.vectorf(mysample))

    @livecoding
    def init_lsl_agentstream(self):
        """ Initialize the AgentCoordinates stream for LSL. """
        info = pylsl.stream_info('SNAP-LSE-AgentCoordinates','Control',(3+3)*max_agents,0,pylsl.cf_float32,'SNAP-LSE-Agentstream' + server_version + str(self.permutation))
        # append some serious meta-data
        channels = info.desc().append_child('channels')
        for agent in [0,1]:
            agent_name = 'Agent' + str(agent)
            for coord in ['X','Y','Z']:
                chn = channels.append_child('channel')
                chn.append_child_value('name',agent_name + 'Position' + coord)
                chn.append_child_value('type','Position' + coord)
                chn.append_child_value('unit','meters')
                chn.append_child_value('object',agent_name)
            for axis in ['X','Y','Z']:
                chn = channels.append_child('channel')
                chn.append_child_value('name',agent_name + 'Velocity' + axis)
                chn.append_child_value('type','Velocity' + axis)
                chn.append_child_value('unit','meters/second')
                chn.append_child_value('object',agent_name)
        self.agent_positions_outlet = pylsl.stream_outlet(info)

    @livecoding
    def update_lsl_agentstate(self):
        """ Push a new sample into the AgentCoordinates stream. """
        mysample = [0]*(3+3)*max_agents
        for k in self.navcrowd.active_indices():
            agent = self.navcrowd.agent_status(k)
            pos = agent.npos
            vel = agent.vel
            mysample[k*6:(k+1)*6] = [pos.getX(),pos.getY(),pos.getZ(),vel.getX(),vel.getY(),vel.getZ()]
        self.agent_positions_outlet.push_sample(pylsl.vectorf(mysample))

