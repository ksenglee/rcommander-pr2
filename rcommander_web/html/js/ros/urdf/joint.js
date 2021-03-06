/*********************************************************************
 *
 * Software License Agreement (BSD License)
 *
 *  Copyright (c) 2010, Robert Bosch LLC.
 *  All rights reserved.
 *
 *  Redistribution and use in source and binary forms, with or without
 *  modification, are permitted provided that the following conditions
 *  are met:
 *
 *   * Redistributions of source code must retain the above copyright
 *     notice, this list of conditions and the following disclaimer.
 *   * Redistributions in binary form must reproduce the above
 *     copyright notice, this list of conditions and the following
 *     disclaimer in the documentation and/or other materials provided
 *     with the distribution.
 *   * Neither the name of the Robert Bosch nor the names of its
 *     contributors may be used to endorse or promote products derived
 *     from this software without specific prior written permission.
 *
 *  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 *  "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 *  LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 *  FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 *  COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
 *  INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
 *  BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 *  LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
 *  CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 *  LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
 *  ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 *  POSSIBILITY OF SUCH DAMAGE.
 *
 *********************************************************************/


/**
 * Class to handle urdf joints
 * @class
 * @augments Class
 */
ros.urdf.Joint = Class.extend(
/** @lends ros.urdf.Joint# */
{
		init:function() {
		
			// members
			this.name = "";
			this.JointTypes = {"unknown" : 0, 
	                   "revolute" : 1, 
	                   "continuous" : 3, 
	                   "prismatic" : 4, 
                     "floating" : 5, 
                     "planar" : 6, 
                     "fixed" : 7};
			this.type = this.JointTypes.unknown;
			this.axis = new ros.urdf.Vector3();
			this.child_link_name = "";
			this.parent_link_name = "";
			this.parent_to_joint_origin_transform = new ros.urdf.Pose();
			this.dynamics = null;
			this.limits = null;
			this.safety = null;
			this.calibration = null;
			this.mimic = null;
		},

// methods
		clear : function ()
		{
			this.name = "";
			this.axis.clear();
			this.child_link_name = "";
			this.parent_link_name = "";
			this.parent_to_joint_origin_transform.clear();
			this.dynamics = null;
			this.limits = null;
			this.safety = null;
			this.calibration = null;
			this.mimic = null;
			this.type = this.JointTypes.unknown;
		},

		initXml : function (xml)
		{
			this.clear();

			// Get Joint Name
			var name = xml.getAttribute("name");
			if (!name)
			{
				ros_error("unnamed joint found");
				return false;
			}
			this.name = name;

			// Get transform from Parent Link to Joint Frame
			var origins = xml.getElementsByTagName("origin");
			if(origins.length==0)
			{
				ros_debug("Joint " + this.name + " missing origin tag under parent describing transform from Parent Link to Joint Frame, (using Identity transform).");
				this.parent_to_joint_origin_transform.clear();
			}
			else
			{
				origin_xml = origins[0];
				if (!this.parent_to_joint_origin_transform.initXml(origin_xml))
				{
					ros_error("Malformed parent origin element for joint " + this.name);
					this.parent_to_joint_origin_transform.clear();
					return false;
				}
			}

			// Get Parent Link
			var parents = xml.getElementsByTagName("parent");
			if(parents.length>0)
			{
				var parent_xml = parents[0];
				var pname = parent_xml.getAttribute("link");
				if (!pname)
					ros_info("no parent link name specified for Joint link " + this.name + ". this might be the root?");
				else
				{
					this.parent_link_name = pname;
				}
			}

			// Get Child Link
			var children = xml.getElementsByTagName("child");
			if(children.length>0)
			{
				var child_xml = children[0];
				var pname = child_xml.getAttribute("link");
				if (!pname)
					ros_info("no child link name specified for Joint link " + this.name);
				else
				{
					this.child_link_name = pname;
				}
			}

			// Get Joint type
			var type_char = xml.getAttribute("type");
			if (!type_char)
			{
				ros_error("joint " + this.name + " has no type, check to see if it's a reference.");
				return false;
			}
			var type_str = type_char;
			if (type_str == "planar")
				this.type = this.JointTypes.planar;
			else if (type_str == "floating")
				this.type = this.JointTypes.floating;
			else if (type_str == "revolute")
				this.type = this.JointTypes.revolute;
			else if (type_str == "continuous")
				this.type = this.JointTypes.continuous;
			else if (type_str == "prismatic")
				this.type = this.JointTypes.prismatic;
			else if (type_str == "fixed")
				this.type = this.JointTypes.fixed;
			else
			{
				ros_error("Joint " + this.name + " has no known type " + type_str);
				return false;
			}

			// Get Joint Axis
			if (this.type != this.JointTypes.floating && this.type != this.JointTypes.fixed)
			{
				// axis
				var axis = xml.getElementsByTagName("axis");
				if(axis.length==0) {
					ros_debug("no axis elemement for Joint link " + this.name + ", defaulting to (1,0,0) axis");
					this.axis = new Vector3(1.0, 0.0, 0.0);
				}
				else{
					var axis_xml = axis[0];
					if (!axis_xml.getAttribute("xyz")) {
						ros_error("no xyz attribute for axis element for Joint link " + this.name);
					}
					else {
						if (!this.axis.initString(axis_xml.getAttribute("xyz")))
						{
							ros_error("Malformed axis element for joint " + this.name);
							this.axis.clear();
							return false;
						}
					}
				}
			}

//			// Get limit
//			TiXmlElement *limit_xml = config->FirstChildElement("limit");
//			if (limit_xml)
//			{
//			limits.reset(new JointLimits);
//			if (!limits->initXml(limit_xml))
//			{
//			ROS_ERROR("Could not parse limit element for joint '%s'", this->name.c_str());
//			limits.reset();
//			return false;
//			}
//			}
//			else if (this->type == REVOLUTE)
//			{
//			ROS_ERROR("Joint '%s' is of type REVOLUTE but it does not specify limits", this->name.c_str());
//			return false;
//			}
//			else if (this->type == PRISMATIC)
//			{
//			ROS_INFO("Joint '%s' is of type PRISMATIC without limits", this->name.c_str());
//			limits.reset();
//			}

//			// Get safety
//			TiXmlElement *safety_xml = config->FirstChildElement("safety_controller");
//			if (safety_xml)
//			{
//			safety.reset(new JointSafety);
//			if (!safety->initXml(safety_xml))
//			{
//			ROS_ERROR("Could not parse safety element for joint '%s'", this->name.c_str());
//			safety.reset();
//			return false;
//			}
//			}

//			// Get calibration
//			TiXmlElement *calibration_xml = config->FirstChildElement("calibration");
//			if (calibration_xml)
//			{
//			calibration.reset(new JointCalibration);
//			if (!calibration->initXml(calibration_xml))
//			{
//			ROS_ERROR("Could not parse calibration element for joint  '%s'", this->name.c_str());
//			calibration.reset();
//			return false;
//			}
//			}

//			// Get Joint Mimic
//			TiXmlElement *mimic_xml = config->FirstChildElement("mimic");
//			if (mimic_xml)
//			{
//			mimic.reset(new JointMimic);
//			if (!mimic->initXml(mimic_xml))
//			{
//			ROS_ERROR("Could not parse mimic element for joint  '%s'", this->name.c_str());
//			mimic.reset();
//			return false;
//			}
//			}

//			// Get Dynamics
//			TiXmlElement *prop_xml = config->FirstChildElement("dynamics");
//			if (prop_xml)
//			{
//			dynamics.reset(new JointDynamics);
//			if (!dynamics->initXml(prop_xml))
//			{
//			ROS_ERROR("Could not parse joint_dynamics element for joint '%s'", this->name.c_str());
//			dynamics.reset();
//			return false;
//			}
//			}

			return true;
		}

});

