%RUN_TWIN Check the twin, run every scenario, show the graphs and save everything.
%   Open this folder in MATLAB and run: run_twin
%   Results: results/latest (newest run) and results/run_<date>_<time> (the last 5 runs).

twin_selftest();
p = twin_params();
if p.calibrated
    fprintf('Using the robot calibration from data/calibration.json\n');
else
    fprintf('No calibration found: using the default robot model\n');
end

outputFolder = twin_results('new');
scenarios = {'straight', 'turn90', 'face_user', 'obstacle'};
logs = cell(size(scenarios));
for k = 1:numel(scenarios)
    name = scenarios{k};
    fprintf('Running %s...\n', name);
    logs{k} = twin_run(name, p);
    withoutControl = twin_run(name, p, struct('control', false));
    rows(k, 1) = twin_save_run(logs{k}, withoutControl, outputFolder); %#ok<SAGROW>
    twin_plot(logs{k}, withoutControl);
    fprintf('%-10s final pose x=%.3f m, y=%.3f m, heading=%.1f deg %s\n', name, logs{k}.x(end), ...
        logs{k}.y(end), rad2deg(logs{k}.theta(end)), logs{k}.stopReason);
end
writetable(struct2table(rows), fullfile(outputFolder, 'summary.csv'));
overview = twin_overview(logs);
exportgraphics(overview, fullfile(outputFolder, 'overview.png'), 'Resolution', 150);

try
    twin_compare([], p, outputFolder);
catch problem
    fprintf('Skipped the comparison with the real robot: %s\n', problem.message);
end
twin_results('publish', outputFolder);
