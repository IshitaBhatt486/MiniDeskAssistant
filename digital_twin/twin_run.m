function log = twin_run(scenario, p, options)
%TWIN_RUN Simulate one scenario with the robot's control loops and safety rules.
%   log = twin_run('straight')    forward with a weaker left motor, heading PID on
%   log = twin_run('turn90')      timed 90 degree turn with turn-rate PID and a weak battery
%   log = twin_run('face_user')   cascaded yaw + rate PID using delayed camera bearings
%   log = twin_run('obstacle')    drive at the mug: slow-down zone, then safety stop
%   log = twin_run(name, p, struct('control', false))   same run without correction

if nargin < 2 || isempty(p), p = twin_params(); end
if nargin < 3, options = struct(); end
useControl = ~isfield(options, 'control') || options.control;
w = twin_world();
rng(1);

s = struct('x', 0.45, 'y', 0.25, 'theta', 0, 'vl', 0, 'vr', 0, 'omega', 0);
duration = 4;
switch scenario
    case 'straight'
        p.leftStrength = 0.9;
    case 'turn90'
        p.leftStrength = 0.75;
        p.rightStrength = 0.75;
        duration = 2.5;
    case 'face_user'
        s.theta = deg2rad(40);
        duration = 5;
    case 'obstacle'
        s = struct('x', 0.50, 'y', 0.42, 'theta', 0, 'vl', 0, 'vr', 0, 'omega', 0);
        duration = 6;
    otherwise
        error('twin_run:scenario', 'Unknown scenario: %s', scenario);
end

n = round(duration / p.dt);
log = struct('scenario', scenario, 't', (0:n-1)' * p.dt, 'x', zeros(n, 1), 'y', zeros(n, 1), ...
    'theta', zeros(n, 1), 'left', zeros(n, 1), 'right', zeros(n, 1), 'setpoint', nan(n, 1), ...
    'measured', nan(n, 1), 'front', zeros(n, 1), 'sonar', zeros(n, numel(p.sonars)), ...
    'stopReason', '', 'world', w, 'params', p);

yawEstimate = s.theta;
yawStart = s.theta;
heading = p.heading;
turnRate = p.turnRate;
yawPid = p.yaw;
facePid = p.faceRate;
turnPerPwm = 2 * p.wheelSpeedAtFull / p.trackWidth;
turnTarget = turnPerPwm * p.speed;
turnTime = (pi / 2) / turnTarget;
cmd = [0 0];
target = nan;
yawHistory = nan(n, 1);
nextControl = 0;
nextCamera = 0;
stopped = false;

for k = 1:n
    t = log.t(k);
    r = twin_sense(s, p, w);
    yawEstimate = yawEstimate + r.gyroZ * p.dt;
    yawHistory(k) = yawEstimate;

    if t >= nextControl && ~stopped
        nextControl = t + p.controlPeriod;
        dt = p.controlPeriod;
        switch scenario
            case 'straight'
                out = 0;
                if useControl
                    [out, heading] = twin_pid(heading, yawStart, yawEstimate, dt);
                end
                cmd = p.speed * [p.leftGain * (1 - out), p.rightGain * (1 + out)];
                log.setpoint(k) = yawStart;
                log.measured(k) = yawEstimate;
            case 'turn90'
                scale = 1;
                if useControl
                    [out, turnRate] = twin_pid(turnRate, turnTarget, abs(r.gyroZ), dt);
                    scale = 1 + out;
                end
                cmd = p.speed * scale * [-1 1] * (t < turnTime);
                log.setpoint(k) = turnTarget;
                log.measured(k) = abs(r.gyroZ);
            case 'face_user'
                if t >= nextCamera && t >= p.cameraLatency
                    nextCamera = t + p.cameraPeriod;
                    captureIndex = max(1, k - round(p.cameraLatency / p.dt));
                    bearing = bearingToUser(s, log, captureIndex, w);
                    target = yawHistory(captureIndex) + bearing;
                end
                cmd = [0 0];
                if useControl && ~isnan(target) && abs(target - yawEstimate) > p.faceDeadband
                    [rateWanted, yawPid] = twin_pid(yawPid, target, yawEstimate, dt);
                    [trim, facePid] = twin_pid(facePid, rateWanted, r.gyroZ, dt);
                    u = rateWanted / turnPerPwm + trim;
                    u = u + sign(u) * p.minTurnPwm;
                    u = max(-p.facePwmLimit, min(p.facePwmLimit, u));
                    cmd = [-u u];
                end
                log.setpoint(k) = target;
                log.measured(k) = yawEstimate;
            case 'obstacle'
                scale = 1;
                if useControl
                    f = (r.sonar(1) - p.stopDistance) / p.slowZone;
                    scale = max(p.minSpeedScale, min(1, f));
                end
                cmd = p.speed * scale * [1 1];
                log.setpoint(k) = p.stopDistance;
                log.measured(k) = r.sonar(1);
        end
    end

    [blocked, reason] = twin_safety(cmd(1), cmd(2), r, p);
    if blocked
        cmd = [0 0];
        stopped = true;
        log.stopReason = reason;
    end
    s = twin_step(s, cmd(1), cmd(2), p, w);

    log.x(k) = s.x;
    log.y(k) = s.y;
    log.theta(k) = s.theta;
    log.left(k) = cmd(1);
    log.right(k) = cmd(2);
    log.front(k) = r.sonar(1);
    log.sonar(k, :) = r.sonar;
end
end

function b = bearingToUser(s, log, index, w)
% Bearing of the person as seen at the capture time.
x = s.x;
y = s.y;
theta = s.theta;
if index < numel(log.t) && log.x(index) ~= 0
    x = log.x(index);
    y = log.y(index);
    theta = log.theta(index);
end
b = atan2(w.user(2) - y, w.user(1) - x) - theta;
b = atan2(sin(b), cos(b));
end
