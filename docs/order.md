1. check if encoders are available for the motor. if not ask if any motor with encoders is available
2. connect the components # pins.md
3. test the pi + motors + sensors with `3Nov-latest.py` # pi.md (done: working)
4. web dashboard (`dashboard/server.py`) and occupancy mapping (`dashboard/server_mapping.py`) # mapping.md (done in sim, calibrate odometry on the robot)
5a. test the camera: `python3 hardware_tests/hardware_test.py camera` # camera.md
5b. test the microphone (via USB sound card): `python3 hardware_tests/hardware_test.py mic` # microphone.md
5. test each sensor on its own: `python3 hardware_tests/hardware_test.py sensors` (pick a sensor, watch its readings) # sensor-tests.md
6. three extra ultrasonic sensors: left/right/rear (`13Nov-multisonar.py`) # multisonar.md (done in sim, wire + test on the robot)
7. chasis # chasis.md
8. encoders #encoders.md
9. full app `deskbot`: camera + YOLO26n (NCNN) + ByteTrack, fusion maps, CLI: `bash scripts/setup.sh`, then `bash scripts/start.sh` # deskbot.md, vision.md, fusion.md (done in sim; on the robot: export the model, measure the camera mount)
10. four processes on four cores (motor / sensors / camera / nav), newest command wins, face the user, detect every 3 frames, glass/reflection handling: `bash scripts/enable-realtime.sh` once, then `bash scripts/start.sh` # runtime.md, fusion.md (done in sim; on the robot: check the Processes card)
11. benchmark: `bash tools/run_benchmarks.sh` (COCO under 11 lighting conditions, Objectron tracking, runtime latency) # benchmark.md
