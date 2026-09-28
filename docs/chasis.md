- get all measurements and then use CADQuery to describe the model in a python file and generate it. a Python-based parametric CAD framework. generate STEP, STL, DXF, 3MF and other CAD formats
- the entire model can live as readable Python code and its parameters can be changed easily
- CadQuery also has a GUI called CQ-editor

1. measure motor length
motor width
motor height
shaft diameter
shaft length
mounting-hole spacing
2. measure wheel diameter
wheel width
hub/shaft interface
3. Measure the Pi body and account for:

USB ports
HDMI
power
camera connector
GPIO

4. L298N
5. battery
length
width
height
wire exit position
6. display
7. camera hole
8. microphone
9. speaker

- Make a "keep-out" box around every component to make space for wiring and components
- a simple cylinerical ovalish differential-drive chassis.(smoothened at the edges)
- add arms
- modular chasis with seperate components that can be joined and taken apart by clicking
- in v1, only print the main body but leave attachment space for the arms, the head(can be filled in later if needed)
- securely constrained motor
- adjustable mounting holes/slots rather than one fixed motor position.
- the wheels are at the sides- use caster wheels- if wheels are small, then put them in the bottom
- put the drive wheels approximately around the robot's center of mass to make the turning easier
- Create mounting holes/standoffs with screws and clickable things so that it can be attached and removed easily
- space for wiring- create cable-routing channels or open regions.
- keep battery low, central and secure because keeping it up will make it unstable by raising the ceter of mass
- make sure that stability is taken into consideration and based on every component that will be added in the future
- Add future mounting points now
- try to keep the components spaced out and positioned according to the approximate weights of each
- do something to make the camera mount seperate(like antennas) so that the camera angle can be adjusted
- desk-edge sensors into the bottom.The sensors need to actually see the surface below the robot, so don't bury them inside the chassis.
- Make it easy to open and rewire/etc
- Add ventilation for Pi and L298N- ventilation slots
- make sure you can still access using ports at the bottom:

USB
HDMI
GPIO
power
microSD
camera connector

- make a spreadsheet of all measurements
- physical envelope
mounting-hole locations
hole diameter
connector locations
connector clearance
cable exit direction
shaft locations
moving parts
heat-generating areas