function w = twin_world()
%TWIN_WORLD The simulated desk: same size and objects as deskbot/robot.py.
%   Origin bottom-left, metres. The top edge is a wall; the other edges are drops.

w.width = 1.2;
w.height = 0.7;
w.circles = [0.93 0.42 0.045;    % mug: x y radius
             1.02 0.13 0.035];   % bottle
w.rects = [0.14 0.44 0.24 0.17]; % book: x y width height
w.user = [0.60 -0.30 0.15];      % person sitting across the desk
end
