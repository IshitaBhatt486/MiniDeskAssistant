| Component                           | Use                           |
| ----------------------------------- | ----------------------------- |
| Raspberry Pi 4                      | Main controller               |
| L298N motor driver                  | Motor power/direction control |
| 2 DC geared motors                  | Left + right drive            |
| 2 wheels                            | Drive                         |
| Separate motor battery/power supply | Motors                        |
| Jumper wires                        | Connections                   |
| Raspberry Pi power supply           | Pi power  (later)             |
| Breadboard                          | Optional                      |
| HC-SR04 ultrasonic sensor           | Front obstacle detection      |
| 3 more HC-SR04 (optional)           | Left, right, rear obstacle detection (`13Nov-multisonar.py`) |
| Raspberry Pi camera module (CSI ribbon) | Vision (`test_camera.py` to check it) |
| Electret microphone capsule (2 wires) | Audio input; needs a USB sound card with a mic jack (`test_microphone.py`) |
| USB sound card (mic jack)           | Powers and digitises the electret mic |
| 2 IR edge sensors (digital output)  | Front + rear desk-edge detection |
| 1 kΩ + 2 kΩ resistors               | Voltage divider for each HC-SR04 ECHO (5 V → 3.3 V), one pair per sensor |

- ask if encoders are available, if not then if any motor with built in encoders is available- why: to measure the distance moved and to rotate the motor accordingly
- if not, then is Optical flow sensor available(measure the distance moved)
- if both available, we can use to complement- sensor fusion
- we will attach them at the base
- if not, then does any of the team members or their friends have a motor with an encoder
- if not, then based on the motor, buy the encoder if below 500