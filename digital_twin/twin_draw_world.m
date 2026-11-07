function twin_draw_world(ax, w)
%TWIN_DRAW_WORLD Desk, objects and person, seen from above.
hold(ax, 'on');
rectangle(ax, 'Position', [0 0 w.width w.height], 'FaceColor', [0.96 0.95 0.92], 'EdgeColor', [0.6 0.6 0.56]);
for k = 1:size(w.rects, 1)
    rectangle(ax, 'Position', w.rects(k, :), 'FaceColor', [0.72 0.70 0.86], 'EdgeColor', 'none');
end
circles = [w.circles; w.user];
for k = 1:size(circles, 1)
    c = circles(k, :);
    rectangle(ax, 'Position', [c(1:2) - c(3), 2 * c(3), 2 * c(3)], 'Curvature', [1 1], ...
        'FaceColor', [0.70 0.80 0.92], 'EdgeColor', 'none');
end
axis(ax, 'equal');
xlim(ax, [-0.1 w.width + 0.1]);
ylim(ax, [-0.5 w.height + 0.1]);
xlabel(ax, 'x (m)');
ylabel(ax, 'y (m)');
end
