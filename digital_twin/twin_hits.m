function hit = twin_hits(w, x, y, inflate)
%TWIN_HITS True when a point touches the wall, an object or the person.
if nargin < 4
    inflate = 0;
end
hit = y >= w.height - inflate;
circles = [w.circles; w.user];
if ~hit
    hit = any(hypot(x - circles(:, 1), y - circles(:, 2)) <= circles(:, 3) + inflate);
end
if ~hit
    r = w.rects;
    hit = any(x >= r(:, 1) - inflate & x <= r(:, 1) + r(:, 3) + inflate & ...
              y >= r(:, 2) - inflate & y <= r(:, 2) + r(:, 4) + inflate);
end
end
