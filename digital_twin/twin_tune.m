function best = twin_tune()
%TWIN_TUNE Try yaw gains for "face the user" and report the best ones for data/companion.json.

p = twin_params();
kpValues = 1.0:0.4:3.4;
kdValues = [0 0.04 0.08 0.16];
cost = nan(numel(kdValues), numel(kpValues));
for i = 1:numel(kdValues)
    for j = 1:numel(kpValues)
        q = p;
        q.yaw.gains = [kpValues(j) p.yaw.gains(2) kdValues(i)];
        log = twin_run('face_user', q);
        valid = ~isnan(log.setpoint);
        e = log.setpoint(valid) - log.measured(valid);
        cost(i, j) = sqrt(mean(e.^2)) + 0.2 * max(0, max(abs(e(end - min(50, numel(e) - 1):end))));
    end
end
[~, index] = min(cost(:));
[i, j] = ind2sub(size(cost), index);
best = struct('yaw_kp', kpValues(j), 'yaw_kd', kdValues(i), 'cost', cost(i, j));
fprintf('Best in the twin: yaw_kp = %.2f, yaw_kd = %.2f\n', best.yaw_kp, best.yaw_kd);
fprintf('Try on the robot with data/companion.json: {"control": {"yaw_kp": %.2f, "yaw_kd": %.2f}}\n', best.yaw_kp, best.yaw_kd);

fig = figure('Name', 'Yaw gain search', 'Color', 'w');
ax = axes(fig);
imagesc(ax, kpValues, 1:numel(kdValues), cost);
yticks(ax, 1:numel(kdValues)); yticklabels(ax, string(kdValues));
xlabel(ax, 'yaw Kp'); ylabel(ax, 'yaw Kd');
title(ax, 'Tracking cost (lower is better)');
colorbar(ax);

outputFolder = twin_results('new');
exportgraphics(fig, fullfile(outputFolder, 'gain_search.png'), 'Resolution', 150);
writetable(struct2table(best), fullfile(outputFolder, 'gain_search.csv'));
twin_results('publish', outputFolder);
end
