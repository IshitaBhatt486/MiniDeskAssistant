function fig = twin_plot(log, baseline, visible)
%TWIN_PLOT Four graphs for one run: path, target vs measured, wheel commands, sonars.
%   twin_plot(log), twin_plot(log, logWithoutControl), twin_plot(log, baseline, 'off').

if nargin < 2, baseline = []; end
if nargin < 3, visible = 'on'; end
blue = [0.16 0.47 0.84];
orange = [0.92 0.41 0.20];
green = [0.11 0.69 0.48];
yellow = [0.93 0.63 0.00];

fig = figure('Name', ['Digital twin: ' log.scenario], 'Color', 'w', 'Visible', visible, 'Position', [100 100 1000 680]);
layout = tiledlayout(fig, 2, 2, 'Padding', 'compact', 'TileSpacing', 'compact');
title(layout, ['Scenario: ' strrep(log.scenario, '_', ' ')]);

ax = nexttile(layout);
twin_draw_world(ax, log.world);
plot(ax, log.x, log.y, 'LineWidth', 2, 'Color', blue, 'DisplayName', 'with control');
if ~isempty(baseline)
    plot(ax, baseline.x, baseline.y, '--', 'LineWidth', 1.5, 'Color', orange, 'DisplayName', 'without control');
end
legend(ax, 'Location', 'best');
title(ax, 'Path on the desk');

ax = nexttile(layout);
valid = ~isnan(log.measured);
plot(ax, log.t(valid), log.setpoint(valid), 'LineWidth', 1.5, 'Color', orange, 'DisplayName', 'target');
hold(ax, 'on');
plot(ax, log.t(valid), log.measured(valid), 'LineWidth', 1.5, 'Color', blue, 'DisplayName', 'measured');
styleAxes(ax, 'Control loop', 'value');

ax = nexttile(layout);
plot(ax, log.t, log.left, 'LineWidth', 1.5, 'Color', blue, 'DisplayName', 'left');
hold(ax, 'on');
plot(ax, log.t, log.right, 'LineWidth', 1.5, 'Color', orange, 'DisplayName', 'right');
styleAxes(ax, 'Wheel commands', 'PWM');

ax = nexttile(layout);
colors = {blue, orange, green, yellow};
hold(ax, 'on');
for k = 1:numel(log.params.sonars)
    plot(ax, log.t, log.sonar(:, k), 'LineWidth', 1.3, 'Color', colors{k}, 'DisplayName', log.params.sonars(k).name);
end
styleAxes(ax, 'Sonar distances', 'm');
end

function styleAxes(ax, heading, unit)
xlabel(ax, 'time (s)');
ylabel(ax, unit);
grid(ax, 'on');
legend(ax, 'Location', 'best');
title(ax, heading);
end
