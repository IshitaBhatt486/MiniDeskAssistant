function r = twin_sense(s, p, w)
%TWIN_SENSE What the robot's sensors read in state s.
%   r.sonar = [front left right rear] (m), r.frontFloor, r.rearFloor, r.gyroZ (rad/s).

c = cos(s.theta);
n = sin(s.theta);
r.sonar = zeros(1, numel(p.sonars));
for k = 1:numel(p.sonars)
    m = p.sonars(k);
    ox = s.x + m.x * c - m.y * n;
    oy = s.y + m.x * n + m.y * c;
    a = s.theta + m.angle;
    d = 0;
    while d < p.maxRange && ~twin_hits(w, ox + cos(a) * d, oy + sin(a) * d)
        d = d + 0.004;
    end
    r.sonar(k) = min(p.maxRange, max(0.02, d + p.sonarNoise * randn));
end
r.frontFloor = onDesk(s.x + p.irOffset * c, s.y + p.irOffset * n);
r.rearFloor = onDesk(s.x - p.irOffset * c, s.y - p.irOffset * n);
r.gyroZ = s.omega + p.gyroBias + p.gyroNoise * randn;

    function yes = onDesk(x, y)
        yes = x >= 0 && x <= w.width && y >= 0 && y <= w.height;
    end
end
