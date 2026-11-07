function p = twin_params(calibrationFile)
%TWIN_PARAMS Parameters of the desk robot's digital twin.
%   p = twin_params() uses ../data/calibration.json when it exists.
%   p = twin_params(file) reads that calibration file instead ('' = none).
%   Values match deskbot/config.py, deskbot/companion/config.py and dashboard/*.py.

here = fileparts(mfilename('fullpath'));
if nargin < 1
    calibrationFile = fullfile(here, '..', 'data', 'calibration.json');
end

% Geometry (m)
p.trackWidth = 0.12;
p.bodyRadius = 0.075;
p.irOffset = 0.07;
p.sonars = struct( ...
    'name', {'front', 'left', 'right', 'rear'}, ...
    'x', {0.06, 0, 0, -0.06}, ...
    'y', {0, 0.065, -0.065, 0}, ...
    'angle', {0, pi/2, -pi/2, pi});
p.maxRange = 2.0;

% Drive model
p.wheelSpeedAtFull = 0.25;   % m/s at 100 % PWM
p.motorTau = 0.08;           % s, wheel speed lag
p.deadZone = 0.0;            % PWM fraction that produces no motion
p.leftStrength = 1.0;        % motor mismatch (set in scenarios to test the controller)
p.rightStrength = 1.0;
p.leftGain = 1.0;            % calibrated correction
p.rightGain = 1.0;

% Sensor noise
p.sonarNoise = 0.002;        % m
p.gyroNoise = 0.002;         % rad/s
p.gyroBias = 0.0;            % rad/s left after calibration

% Safety rules
p.stopDistance = 0.20;
p.sideStopDistance = 0.08;

% Timing
p.dt = 0.01;                 % physics step, s
p.controlPeriod = 0.04;      % 25 Hz
p.facePeriod = 0.05;         % 20 Hz
p.cameraPeriod = 0.10;       % new detection every 100 ms
p.cameraLatency = 0.12;      % s from capture to result
p.speed = 0.5;

% PID gains: [Kp Ki Kd], limits: [low high]
p.heading = struct('gains', [1.2 0.3 0.05], 'limits', [-0.3 0.3]);
p.turnRate = struct('gains', [0.15 0.35 0], 'limits', [-0.4 0.8]);
p.yaw = struct('gains', [2.2 0.1 0.08], 'limits', [-2 2]);
p.faceRate = struct('gains', [0.08 0.25 0], 'limits', [-0.8 0.8]);
p.faceDeadband = deg2rad(3);
p.facePwmLimit = 0.8;
p.minTurnPwm = 0.0;
p.slowZone = 0.25;
p.minSpeedScale = 0.45;

p.calibrated = false;
if ~isempty(calibrationFile) && isfile(calibrationFile)
    cal = jsondecode(fileread(calibrationFile));
    if isfield(cal, 'drive')
        d = cal.drive;
        if isfield(d, 'wheel_speed_at_full'), p.wheelSpeedAtFull = d.wheel_speed_at_full; end
        if isfield(d, 'turn_rate_per_pwm')
            p.trackWidth = 2 * p.wheelSpeedAtFull / d.turn_rate_per_pwm;
        end
        if isfield(d, 'min_turn_pwm')
            p.minTurnPwm = d.min_turn_pwm;
            p.deadZone = d.min_turn_pwm;
        end
        if isfield(d, 'left_gain'), p.leftGain = d.left_gain; end
        if isfield(d, 'right_gain'), p.rightGain = d.right_gain; end
        p.calibrated = true;
    end
end
end
