function s = twin_step(s, leftCmd, rightCmd, p, w)
%TWIN_STEP Advance the robot by one physics step.
%   State s: x, y, theta (unwrapped), vl, vr. Commands are PWM values, -1..1.

target = [wheelSpeed(leftCmd * p.leftStrength), wheelSpeed(rightCmd * p.rightStrength)];
alpha = 1 - exp(-p.dt / p.motorTau);
s.vl = s.vl + alpha * (target(1) - s.vl);
s.vr = s.vr + alpha * (target(2) - s.vr);

v = (s.vl + s.vr) / 2;
omega = (s.vr - s.vl) / p.trackWidth;
s.theta = s.theta + omega * p.dt;
nx = s.x + v * cos(s.theta) * p.dt;
ny = s.y + v * sin(s.theta) * p.dt;
if ~twin_hits(w, nx, ny, p.bodyRadius)
    s.x = nx;
    s.y = ny;
end
s.omega = omega;

    function speed = wheelSpeed(u)
        u = max(-1, min(1, u));
        effective = max(0, abs(u) - p.deadZone) / max(1e-6, 1 - p.deadZone);
        speed = sign(u) * effective * p.wheelSpeedAtFull;
    end
end
