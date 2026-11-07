function fig = twin_overview(logs, visible)
%TWIN_OVERVIEW Every scenario's path on one page. logs is a cell array from twin_run.

if nargin < 2, visible = 'on'; end
fig = figure('Name', 'Digital twin overview', 'Color', 'w', 'Visible', visible, 'Position', [100 100 1000 680]);
layout = tiledlayout(fig, 'flow', 'Padding', 'compact', 'TileSpacing', 'compact');
title(layout, 'All scenarios');
for k = 1:numel(logs)
    ax = nexttile(layout);
    twin_draw_world(ax, logs{k}.world);
    plot(ax, logs{k}.x, logs{k}.y, 'LineWidth', 2, 'Color', [0.16 0.47 0.84]);
    plot(ax, logs{k}.x(end), logs{k}.y(end), 'o', 'MarkerFaceColor', [0.92 0.41 0.20], 'MarkerEdgeColor', 'w');
    title(ax, strrep(logs{k}.scenario, '_', ' '));
end
end
