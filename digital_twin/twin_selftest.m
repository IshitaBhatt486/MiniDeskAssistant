function twin_selftest()
%TWIN_SELFTEST Check the twin's physics and control behaviour. Errors if something is wrong.

p = twin_params('');
p.sonarNoise = 0;
p.gyroNoise = 0;
w = twin_world();

% Straight line at full command: 0.25 * 0.5 m/s, after the motor lag.
s = struct('x', 0.3, 'y', 0.3, 'theta', 0, 'vl', 0, 'vr', 0, 'omega', 0);
for k = 1:200
    s = twin_step(s, 0.5, 0.5, p, w);
end
assert(abs(s.x - 0.3 - 0.125 * (2 - p.motorTau)) < 0.005, 'straight-line distance');
assert(abs(s.y - 0.3) < 1e-9, 'straight line stays straight');

% Positive yaw is a left turn.
s = struct('x', 0.3, 'y', 0.3, 'theta', 0, 'vl', 0, 'vr', 0, 'omega', 0);
for k = 1:100
    s = twin_step(s, -0.5, 0.5, p, w);
end
assert(s.theta > 1, 'left turn increases heading');

% PID matches the conventions of simple-pid.
[u, c] = twin_pid(struct('gains', [2 1 0], 'limits', [-1 1]), 1, 0.9, 0.1);
assert(abs(u - 0.21) < 1e-9 && abs(c.integral - 0.01) < 1e-9, 'PID output');

% Safety rules.
r = struct('sonar', [0.1 1 1 1], 'frontFloor', true, 'rearFloor', true, 'gyroZ', 0);
assert(twin_safety(0.5, 0.5, r, p), 'front obstacle stops forward');
assert(~twin_safety(-0.5, -0.5, r, p), 'reversing away is allowed');

% The controllers do better than no control.
with = twin_run('straight', p);
without = twin_run('straight', p, struct('control', false));
assert(abs(with.y(end) - with.y(1)) < abs(without.y(end) - without.y(1)), 'heading PID reduces drift');

with = twin_run('turn90', p);
without = twin_run('turn90', p, struct('control', false));
assert(abs(with.theta(end) - pi / 2) < abs(without.theta(end) - pi / 2), 'rate PID improves a weak-battery turn');

log = twin_run('face_user', p);
valid = find(~isnan(log.setpoint), 1, 'last');
assert(abs(log.setpoint(valid) - log.measured(valid)) < deg2rad(6), 'robot ends up facing the user');

log = twin_run('obstacle', p);
assert(strcmp(log.stopReason, 'front obstacle'), 'safety rule stops at the object');

fprintf('All digital twin checks passed.\n');
end
