function [u, c] = twin_pid(c, setpoint, measured, dt)
%TWIN_PID One PID step, matching the simple-pid library used on the robot:
%   integral is clamped to the output limits, derivative acts on the measurement.
%   Create c with: c = struct('gains', [Kp Ki Kd], 'limits', [low high]).

if ~isfield(c, 'integral') || isempty(c.integral)
    c.integral = 0;
    c.last = measured;
end
e = setpoint - measured;
c.integral = clamp(c.integral + c.gains(2) * e * dt);
d = -c.gains(3) * (measured - c.last) / dt;
c.last = measured;
u = clamp(c.gains(1) * e + c.integral + d);

    function y = clamp(x)
        y = max(c.limits(1), min(c.limits(2), x));
    end
end
