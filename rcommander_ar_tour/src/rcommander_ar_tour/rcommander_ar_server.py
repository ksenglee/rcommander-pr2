#import roslib; roslib.load_manifest('rcommander_web')
import roslib; roslib.load_manifest("rcommander_ar_tour")
import rospy
import actionlib
import std_msgs.msg as stdm

import interactive_markers.interactive_marker_server as ims
import interactive_markers.menu_handler as mh
import ar_pose.msg as ar_msg
from rcommander_web.srv import ActionInfo, ActionInfoResponse

import rcommander_web.msg as rmsg
#from rcommander_web.msg import *
#import rcommander_ar_pose.utils as rap
import rcommander_pr2_gui.tf_utils as tfu
#import rcommander.graph_model as gm

from PyQt4 import QtCore#, QtGui
#import sys
#import signal
import os
import os.path as pt
import numpy as np


import rcommander_web.rcommander_auto_server as ras
import tf
import cPickle as pk
import functools as ft

import re
import copy
from threading import RLock

DEFAULT_LOC = [[0.,0.,0.], [0.,0.,0.,1.]]

def interactive_marker(name, pose, scale):
    int_marker = ims.InteractiveMarker()
    int_marker.header.frame_id = "/map"
    int_marker.pose.position.x = pose[0][0]
    int_marker.pose.position.y = pose[0][1]
    int_marker.pose.position.z = pose[0][2]
    int_marker.pose.orientation.x = pose[1][0]
    int_marker.pose.orientation.y = pose[1][1]
    int_marker.pose.orientation.z = pose[1][2]
    int_marker.pose.orientation.w = pose[1][2]
    
    int_marker.scale = scale
    int_marker.name = name
    int_marker.description = name
    return int_marker

def make_rviz_marker(scale):
    marker = ims.Marker()
    marker.type = ims.Marker.SPHERE
    marker.scale.x = scale * 0.45
    marker.scale.y = scale * 0.45
    marker.scale.z = scale * 0.45
    marker.color = stdm.ColorRGBA(.5,.5,.5,1)
    return marker

def make_sphere_control(name, scale):
    control =  ims.InteractiveMarkerControl()
    control.name = name + '_sphere'
    control.always_visible = True
    control.markers.append(make_rviz_marker(scale))
    control.interaction_mode = ims.InteractiveMarkerControl.BUTTON
    return control

def make_control_marker():
    control = ims.InteractiveMarkerControl()
    control.orientation.x = 0
    control.orientation.y = 0
    control.orientation.z = 0
    control.orientation.w = 1
    control.interaction_mode = ims.InteractiveMarkerControl.MOVE_AXIS
    return control

def make_directional_controls(name):
    x_control = make_control_marker()
    x_control.orientation.x = 1
    x_control.name = name + "_move_x"

    y_control = make_control_marker()
    y_control.orientation.y = 1
    y_control.name = name + "_move_y"

    z_control = make_control_marker()
    z_control.orientation.z = 1
    z_control.name = name + "_move_z"

    return [x_control, y_control, z_control]


def feedback_to_string(ftype):
    names = ['keep_alive', 'pose_update', 
             'menu_select', 'button_click',
             'mouse_down', 'mouse_up']
    fb = ims.InteractiveMarkerFeedback
    consts = [fb.KEEP_ALIVE, fb.POSE_UPDATE,
                fb.MENU_SELECT, fb.BUTTON_CLICK,
                fb.MOUSE_DOWN, fb.MOUSE_UP]

    for n, value in zip(names, consts):
        if ftype == value:
            return n

    return 'invalid type'

def pose_to_tup(p):
    return [p.position.x, p.position.y, p.position.z], \
            [p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w]

##
# @param callback is a function: f(menu_item, full_action_path)
def menu_handler_from_action_tree(action_tree, callback):
    handler = mh.MenuHandler()
    menu_handler_from_action_tree_helper(handler, action_tree, callback)
    return handler

# {'path':   full path
#  'actions': [{another folder}, {another folder2}, rcom_file}
def menu_handler_from_action_tree_helper(handler, action_tree, callback, parent=None):
    base_path = action_tree['path']
    for action in action_tree['actions']:
        if isinstance(action, dict):
            submenu = handler.insert(action['path'], parent=parent)
            menu_handler_from_action_tree_helper(handler, action, callback, parent=submenu)
        else:
            action_name = os.path.split(action)[1]
            handler.insert(action_name, parent=parent, callback=ft.partial(callback, action_name, action))

def TagDatabase_load(name):
    pickle_file = open(name, 'r')
    db = pk.load(pickle_file)
    pickle_file.close()
    tdb = TagDatabase()
    tdb.database = db
    tdb.modified = False
    print 'database', db
    return tdb

class TagDatabase:
        
    def __init__(self):
        self.modified = True
        self.database = {}
        #self.insert('placeholder')

    ##
    # @param tagid
    # @param location pose stamped in the frame of the tag
    # @param behavior
    # @return None
    def insert(self, tagid, ar_location=DEFAULT_LOC, target_location=DEFAULT_LOC, behavior=None):
        self.database[tagid] = {'ar_location': ar_location, 'target_location': target_location, 'behavior': behavior}
        self.modified = True

    ##
    # @param tagid
    # @erturn dict with keys 'location', 'behavior'
    def get(self, tagid):
        return self.database[tagid].copy()

    def update_target_location(self, tagid, location):
        self.database[tagid]['target_location'] = location
        self.modified = True

    def remove(self, tagid):
        self.database.pop(tagid)
        self.modified = True

    def update_behavior(self, tagid, behavior):
        self.database[tagid]['behavior'] = behavior
        self.modified = True

    def tag_ids(self):
        return self.database.keys()

    def has_id(self, tagid):
        return tagid in self.database.keys()

    def save(self, name):
        if self.modified:
            self.modified = False
            pickle_file = open(name, 'w')
            pk.dump(self.database, pickle_file)
            pickle_file.close()
            rospy.loginfo('Saved tag database to %s.'% name)

class MarkerDisplay:

    def __init__(self, tagid, server, tag_database, tf_listener, server_lock):
        self.tagid = tagid

        self.server_lock = server_lock
        self.server = server
        self.tag_database = tag_database
        self.target_marker = None
        self.ar_marker = None

        self.make_ar_marker()
        self.has_point = False
        self.tf_listener = tf_listener
        self.menu = None

    def remove_all_markers(self):
        self.server_lock.acquire()
        if self.ar_marker != None:
            self.server.erase(self.ar_marker.name)

        if self.target_marker != None:
            self.server.erase(self.target_marker.name)
        self.server_lock.release()

    def get_id_numb(self):
        idnumb = self.tagid.split('_')
        return int(idnumb[-1])

    def make_ar_marker(self, scale=.2):
        name = 'ar_' + self.tagid
        entry = self.tag_database.get(self.tagid)
        pose = entry['ar_location']

        int_marker = interactive_marker(name, (pose[0], (0,0,0,1)), scale)
        if entry['behavior'] != None:
            behavior_name = pt.split(entry['behavior'])[1]
            int_marker.description = ('%s (tag #%d)' % (behavior_name, self.get_id_numb()))
        else:
            int_marker.description = 'Tag #%d' % self.get_id_numb() 
        int_marker.controls += [make_sphere_control(name, int_marker.scale)]
        int_marker.controls[0].markers[0].color = stdm.ColorRGBA(0,1,0,.5)
        self.server_lock.acquire()
        self.server.insert(int_marker, self.marker_cb)
        self.server_lock.release()
        self.ar_marker = int_marker

    def update_ar_marker(self, behavior_name):

        self.server_lock.acquire()
        self.server.erase(self.ar_marker.name)
        self.ar_marker.description = ('%s (tag #%d)' % (behavior_name, self.get_id_numb()))
        self.server.insert(self.ar_marker)
        self.server_lock.release()

    def set_menu(self, menu_handler):
        self.menu = menu_handler
        if not self.has_point:
            return
        else:
            self.server_lock.acquire()
            self.server.erase(self.target_marker.name)
            self.server_lock.release()
            self._make_menu()

    def _make_menu(self):
        menu_control = ims.InteractiveMarkerControl()
        menu_control.interaction_mode = ims.InteractiveMarkerControl.MENU
        menu_control.description=""
        menu_control.name = self.tagid + '_menu'
        menu_control.markers.append(copy.deepcopy(self.target_marker.controls[0].markers[0]))
        menu_control.always_visible = True
        self.target_marker.controls.append(copy.deepcopy(menu_control))

        self.server_lock.acquire()
        self.server.insert(self.target_marker, self.marker_cb)
        self.menu.apply(self.server, self.target_marker.name)
        self.server_lock.release()

    def make_target_marker(self, name, pose, scale=.2):
        int_marker = interactive_marker(name, (pose[0], (0,0,0,1)), scale)
        int_marker.header.frame_id = 'map' #self.tagid
        int_marker.description = ''
        int_marker.controls.append(make_sphere_control(name, scale/2.))
        int_marker.controls[0].markers[0].color = stdm.ColorRGBA(1,0,0,.5)
        int_marker.controls += make_directional_controls(name)

        self.server_lock.acquire()
        self.server.insert(int_marker, self.marker_cb)
        self.server_lock.release()
        self.target_marker = int_marker
        if self.menu != None:
            self._make_menu()

    def toggle_point(self):
        self.server_lock.acquire()
        if self.has_point:
            print 'erasing'
            self.server.erase(self.target_marker.name)
        else:
            print 'making target marker'
            p_ar = self.tag_database.get(self.tagid)['target_location']
            m_ar = tfu.tf_as_matrix(p_ar)
            map_T_ar = tfu.transform('map', self.tagid, self.tf_listener, t=0)
            p_map = tfu.matrix_as_tf(map_T_ar * m_ar)
            self.make_target_marker('target_' + self.tagid, p_map)

        print 'applying changes'
        self.server.applyChanges()
        self.has_point = not self.has_point
        self.server_lock.release()

    def marker_cb(self, feedback):
        name = feedback.marker_name
        ar_match = re.search('^ar_', name)
        target_match = re.search('^target_', name)

        print 'called'
        if ar_match != None and feedback.event_type == ims.InteractiveMarkerFeedback.BUTTON_CLICK:
            print 'lock acq'
            self.toggle_point()
            print 'toggle!'

        if target_match != None and feedback.event_type == ims.InteractiveMarkerFeedback.POSE_UPDATE:
            m_ar = tfu.tf_as_matrix(pose_to_tup(feedback.pose))
            ar_T_map = tfu.transform(self.tagid, 'map', self.tf_listener, t=0)
            p_ar = tfu.matrix_as_tf(ar_T_map * m_ar)
            self.tag_database.update_target_location(self.tagid, p_ar)
        print 'exited'


class ARServer:

    def __init__(self, robot, tf_listener, path_to_rcommander_files, tag_database_name):
        #rospy.init_node('ar_server')

        self.current_task_frame = None
        self.tag_database_name = tag_database_name
        self.path_to_rcommander_files = path_to_rcommander_files
        self.robot = robot
        self.ar_lock = RLock()
        self.broadcaster = tf.TransformBroadcaster()
        if tf_listener == None:
            self.tf_listener = tf.TransformListener()
        else:
            self.tf_listener = tf_listener

        self.start_list_service()
        self.start_marker_server()
        self.start_execution_action()
        self.main_directory_watch_cb(self.path_to_rcommander_files)

    def start_marker_server(self):
        self.SERVER_NAME = 'ar_server'
        self.marker_server = ims.InteractiveMarkerServer(self.SERVER_NAME)
        #Load the database
        try:
            self.tag_database = TagDatabase_load(self.tag_database_name)
            rospy.loginfo('Loaded %s.' % self.tag_database_name)
        except Exception, e:
            self.tag_database = TagDatabase()
            rospy.loginfo('Error loading %s. Creating new database.' % self.tag_database_name)

        #make the default markers
        self.ar_markers = {}
        for tagid in self.tag_database.tag_ids():
            self.create_marker_for_tag(tagid)
        self.marker_server.applyChanges()

        #Subscribe to AR Pose to determine marker visibility
        self.ar_pose_sub = rospy.Subscriber("ar_pose_marker", ar_msg.ARMarkers, self.ar_marker_cb)
        self.marker_visibility = {}
        print 'Ready!'

    def start_list_service(self):
        #For listing / serving actions
        self.loaded_actions = {}
        self.actions_tree = {'path': self.path_to_rcommander_files, 'actions':[]}
        self.main_dir_watcher = ras.WatchDirectory(self.path_to_rcommander_files, self.main_directory_watch_cb)
        rospy.Service('list_rcommander_actions', ActionInfo, self.list_action_cb)

    def start_execution_action(self):
        self.actserv = actionlib.SimpleActionServer('run_rcommander_action_web', rmsg.RunScriptAction, 
                            execute_cb=self.execute_cb, auto_start=False)
        self.actserv.start()

    #####################################################################
    # All callbacks
    #####################################################################
    #AR Version
    def main_directory_watch_cb(self, main_path_name):
        rospy.loginfo('main_directory_watch_cb: rescanning ' + self.path_to_rcommander_files)
        actions = ras.find_all_actions(self.path_to_rcommander_files)
        self.loaded_actions, self.actions_tree = self.load_action_from_found_paths(actions)
        self.insert_locations_folder()
        self.insert_database_actions()

        rospy.loginfo('All actions found\n %s \n' % str(self.loaded_actions.keys()))

        #Refresh the menu objects on each AR marker
        self.ar_lock.acquire()
        for marker_name in self.ar_markers.keys():
            menu_handler = menu_handler_from_action_tree(self.actions_tree, ft.partial(self.ar_menu_callback, marker_name))
            self.ar_markers[marker_name].set_menu(menu_handler)
        self.marker_server.applyChanges()
        self.ar_lock.release()

    def list_action_cb(self, req):
        path = req.path
        if path == '.':
            path = self.path_to_rcommander_files

        fnames, fpaths, anames, apaths = self.list_actions_and_folders_at_path(path, self.actions_tree)
        forder = np.argsort(fnames)
        fnames = np.array(fnames)[forder].tolist()
        fpaths = np.array(fpaths)[forder].tolist()
        
        aorder = np.argsort(anames)
        anames = np.array(anames)[aorder].tolist()
        apaths = np.array(apaths)[aorder].tolist()

        rospy.loginfo('responded to %s' % path)
        return ActionInfoResponse(fnames, fpaths, anames, apaths)

    def execute_cb(self, goal):
        rospy.loginfo('Executing: ' + goal.action_path)
        self.loaded_actions[goal.action_path]['marker_server'].execute(self.actserv)

    def ar_marker_cb(self, msg):
        self.marker_visibility = {}
        for marker in msg.markers:
            self.marker_visibility['4x4_' + str(marker.id)] = True

    def ar_menu_callback(self, marker_name, menu_item, full_action_path, int_feedback):
        self.ar_lock.acquire()
        print 'menu called back on', marker_name, menu_item, full_action_path#, int_feedback
        marker_disp = self.ar_markers[marker_name]
        #Record this in DB
        self.tag_database.update_behavior(marker_disp.tagid, full_action_path)
        #Reset the AR marker
        marker_disp.update_ar_marker(menu_item)
        self.marker_server.applyChanges()
        self.ar_lock.release()

    #####################################################################
    # Functions for maintaining action directories
    #####################################################################
    def _load_action_at_path(self, action):
        rospy.loginfo('Loading ' + action)
        #action_path = os.path.join(self.path_to_rcommander_files, action)
        action_path = action
        for i in range(4):
            try:
                load_dict = {'marker_server':  ras.ScriptedActionServer(action, action_path, self.robot),
                             'watcher': ras.WatchDirectory(action_path, self.sub_directory_changed_cb)}
                rospy.loginfo('Successfully loaded ' + action)
                return load_dict
            except IOError, e:
                rospy.loginfo(str(e))
                rospy.loginfo('IOError encountered, retrying.')
                rospy.sleep(3)

    def sub_directory_changed_cb(self, action_path_name):
        action_path_name = str(action_path_name)
        action_name = pt.split(action_path_name)[1]
        rospy.loginfo('action_name ' + action_name)
        rospy.loginfo('sub_directory_changed_cb: ' + action_name)
        self.loaded_actions[action_name] = self._load_action_at_path(action_name)

    ##
    # Using the recursive dictionary listing in actions_tree
    # goes through and load each found action into memory.
    def load_action_from_found_paths(self, actions_tree):
        loaded_actions = {}
        pruned_tree = {'path': actions_tree['path'], 'actions':[]}

        for action in actions_tree['actions']:
            if isinstance(action, dict):
                sub_loaded_actions, sub_pruned_tree = self.load_action_from_found_paths(action)
                if len(sub_loaded_actions.keys()) > 0:
                    for k in sub_loaded_actions.keys():
                        loaded_actions[k] = sub_loaded_actions[k]
                    pruned_tree['actions'].append(sub_pruned_tree)
            else:
                if self.loaded_actions.has_key(action):
                    loaded_actions[action] = self.loaded_actions[action]
                    pruned_tree['actions'].append(action)
                else:
                    loaded_action = self._load_action_at_path(action)
                    if loaded_action != None:
                        loaded_actions[action] = loaded_action
                        pruned_tree['actions'].append(action)
                    else:
                        rospy.loginfo('Failed to load ' + action)

        return loaded_actions, pruned_tree

    def insert_locations_folder(self):
        has_locations_folder = False
        for action in self.action_tree['actions']:
            if isinstance(action, dict) and action['path'] == 'Locations':
                has_locations_folder = True
        if not has_locations_folder:
            self.action_tree['actions'].append({'path':'Locations', 'actions':[]})

    def get_locations_tree(self):
        for action in self.action_tree['actions']:
            if isinstance(action, dict) and action['path'] == 'Locations':
                return action

    def insert_database_actions(self):
        #loaded actions is keyed with the full behavior path
        locations_tree = self.get_locations_tree()
        #insert individual action from db
        for tagid in self.tag_database.tag_ids():
            entry = self.tag_database.get(tagid)
            if entry['behavior'] != None:
                action_path = pt.join('Locations', entry['behavior'])
                self.loaded_actions[action_path] = self.loaded_actions[entry['behavior']]
                locations_tree['actions'] += [action_path]


    ##
    # Creates a directory listing by descending the actions tree 
    def list_actions_and_folders_at_path(self, path, actions_tree):
        path = os.path.normpath(path)
        fnames, fpaths = [], []
        anames, apaths = [], []

        splitted = path.split(os.path.sep)
        if actions_tree['path'] == splitted[0]:
            if len(splitted) == 1:
                for a in actions_tree['actions']:
                    if isinstance(a, dict):
                        fnames.append(a['path'])
                        fpaths.append(os.path.join(path, a['path']))
                    else:
                        anames.append(os.path.split(a)[1])
                        apaths.append(a)
                return fnames, fpaths, anames, apaths
            else:
                for a in actions_tree['actions']:
                    if isinstance(a, dict) and a['path'] == splitted[1]:
                        fnames, fpaths, anames, apaths = self.list_actions_and_folders_at_path(os.path.join(*splitted[1:]), a)
                        fpaths = [os.path.join(splitted[0], fn) for fn in fpaths]
                        return fnames, fpaths, anames, apaths 

        return fnames, fpaths, anames, apaths
    #####################################################################
    # Task frame management
    #####################################################################
    def set_task_frame(self, tagid):
        self.current_task_frame = tagid

    def publish_task_frame_transform(self):
        if self.current_task_frame != None:
            #is marker visible?
            # map -- robot -- ar -- taskframe
            # taskframe -- ar -- map -- robot
            # either way we want to publish only a task frame -- ar frame
            entry = self.tag_database.get(self.current_task_frame)
            target_location, _ = entry['target_location']
            self.broadcaster.sendTransform(target_location, [0,0,0,1], rospy.Time.now(), 'task_frame', self.current_task_frame)

    #####################################################################
    # Functions for maintaining action directories
    #####################################################################
    def remove_marker_for_tag(self, tagid):
        self.ar_markers[tagid].remove_all_markers()
        self.ar_markers.pop(tagid)

    def create_marker_for_tag(self, tagid):
        if not self.ar_markers.has_key(tagid):
            display = MarkerDisplay(tagid, self.marker_server, self.tag_database, self.tf_listener, self.ar_lock)
            self.ar_markers[tagid] = display
            menu_handler = menu_handler_from_action_tree(self.actions_tree, ft.partial(self.ar_menu_callback, tagid))
            self.ar_markers[tagid].set_menu(menu_handler)
        else:
            print 'Marker', tagid, 'exists! Ignoring create_marker_for_tag call.'

    def _keep_frames_updated(self):
        visible = self.marker_visibility.keys()
        #Publish frames that are not visible
        for tagid in self.tag_database.tag_ids():
            if not (tagid in visible):
                db_entry = self.tag_database.get(tagid)
                if db_entry['behavior'] == None:
                    #rospy.loginfo('Removing %s from db because no one defined a behavior for it.' % tagid)
                    self.tag_database.remove(tagid)
                    self.remove_marker_for_tag(tagid)
                else:
                    position, orientation = self.tag_database.get(tagid)['ar_location']
                    self.broadcaster.sendTransform(position, orientation, rospy.Time.now(), tagid, '/map')
                    #print tagid, ' is not visible. creating transforms.'
        
        #make sure all visible frames are in database
        markers_changed = False
        for tagid in visible:
            try:
                ar_location = self.tf_listener.lookupTransform('map', tagid, rospy.Time(0))
                if not self.tag_database.has_id(tagid):
                    #rospy.loginfo('Inserted %s into database.' % tagid)
                    self.tag_database.insert(tagid, ar_location)
                    self.create_marker_for_tag(tagid)
                    markers_changed = True
                else:
                    self.tag_database.get(tagid)['ar_location'] = ar_location
            except tf.ExtrapolationException, e:
                print 'exception', e
            except tf.ConnectivityException, e:
                print 'exception', e
            except tf.LookupException, e:
                print 'exception', e.__class__

        if markers_changed:
            self.marker_server.applyChanges()

    def _save_database(self):
        self.tag_database.save(self.tag_database_name)

    def step(self, timer_obj):
        print 'step',
        self.ar_lock.acquire()
        self._keep_frames_updated()
        self.publish_task_frame_transform()
        if (self.i % (5*5) == 0):
            self._save_database()
        self.i += 1
        self.ar_lock.release()
        print 'ped'

    def start(self):
        self.i = 0
        rospy.Timer(rospy.Duration(.1), self.step)


def run(robot, tf_listener, path_to_rcommander_files, tag_database_name='ar_tag_database.pkl'):
    import sys
    from PyQt4 import QtCore#, QtGui
    import signal

    #def sigint_handler(*args):
    #    QtCore.QCoreApplication.quit()

    app = QtCore.QCoreApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    #timer = QtCore.QTimer() #Apparently only needed for apps with X present
    #timer.start(500)
    #timer.timeout.connect(lambda: None)
    #signal.signal(signal.SIGINT, sigint_handler)

    arserver = ARServer(robot, tf_listener, path_to_rcommander_files, tag_database_name)
    arserver.start()

    rospy.loginfo('RCommander AR Tour Server up!')
    app.exec_()
