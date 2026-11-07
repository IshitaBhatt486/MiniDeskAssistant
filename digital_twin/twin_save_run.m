function m = twin_save_run(log, baseline, folder)
%TWIN_SAVE_RUN Save one scenario's graphs, animation and data. Returns its summary numbers.

name = log.scenario;
fig = twin_plot(log, baseline, 'off');
exportgraphics(fig, fullfile(folder, [name '_graphs.png']), 'Resolution', 150);
close(fig);
twin_animate(log, fullfile(folder, [name '_animation.gif']), struct('visible', 'off'));

data = table(log.t, log.x, log.y, rad2deg(log.theta), log.left, log.right, log.setpoint, log.measured, ...
    log.sonar(:, 1), log.sonar(:, 2), log.sonar(:, 3), log.sonar(:, 4), 'VariableNames', ...
    {'time_s', 'x_m', 'y_m', 'heading_deg', 'wheel_left', 'wheel_right', 'target', 'measured', ...
     'front_m', 'left_m', 'right_m', 'rear_m'});
writetable(data, fullfile(folder, [name '_data.csv']));

valid = ~isnan(log.setpoint) & ~isnan(log.measured);
difference = log.setpoint(valid) - log.measured(valid);
m = struct('scenario', string(name), 'final_x_m', log.x(end), 'final_y_m', log.y(end), ...
    'final_heading_deg', rad2deg(log.theta(end)), 'distance_m', sum(hypot(diff(log.x), diff(log.y))), ...
    'rms_error', sqrt(mean(difference .^ 2)), 'final_error', abs(difference(end)), 'stop_reason', string(log.stopReason));
end
