function [blocked, reason] = twin_safety(leftCmd, rightCmd, r, p)
%TWIN_SAFETY The motor process's safety rules (deskbot/runtime/procs.py + dashboard/multisonar.py).

v = (leftCmd + rightCmd) / 2;
w = (rightCmd - leftCmd) / 2;
blocked = false;
reason = '';
if v == 0 && w == 0
    return
end
if abs(w) >= abs(v)                     % turning on the spot
    if ~(r.frontFloor && r.rearFloor)
        blocked = true; reason = 'edge while turning';
    elseif min(r.sonar(2:3)) <= p.sideStopDistance
        blocked = true; reason = 'side obstacle';
    end
elseif v > 0
    if ~r.frontFloor
        blocked = true; reason = 'front edge';
    elseif r.sonar(1) <= p.stopDistance
        blocked = true; reason = 'front obstacle';
    end
else
    if ~r.rearFloor
        blocked = true; reason = 'rear edge';
    elseif r.sonar(4) <= p.stopDistance
        blocked = true; reason = 'rear obstacle';
    end
end
end
