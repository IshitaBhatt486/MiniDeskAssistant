function result = twin_compare(sessionFolder, p, outputFolder)
%TWIN_COMPARE Replay a real run through the twin and measure how closely they agree.
%   result = twin_compare()            newest folder in ../outputs that has telemetry
%   result = twin_compare(folder)      a specific outputs/<session> folder
%   The logged wheel commands drive the model; heading is compared with the IMU, and
%   position with the robot's own wheel odometry (it has no absolute position sensor).
%   The figure and numbers are saved to outputFolder, or to a new results run.

if nargin < 2 || isempty(p), p = twin_params(); end
if nargin < 1 || isempty(sessionFolder)
    sessionFolder = newestSession();
end
T = readtable(fullfile(sessionFolder, 'telemetry.csv'));
if height(T) < 5
    error('twin_compare:short', 'Not enough telemetry in %s', sessionFolder);
end

w = twin_world();
w.circles = zeros(0, 3); w.rects = zeros(0, 4); w.user = zeros(0, 3); w.height = inf;   % replay ignores collisions
s = struct('x', T.x(1), 'y', T.y(1), 'theta', deg2rad(startHeading(T)), 'vl', 0, 'vr', 0, 'omega', 0);
n = height(T);
x = zeros(n, 1); y = zeros(n, 1); theta = zeros(n, 1);
x(1) = s.x; y(1) = s.y; theta(1) = s.theta;
left = fillmissing(T.wheel_left, 'constant', 0);
right = fillmissing(T.wheel_right, 'constant', 0);
for k = 2:n
    steps = max(1, round((T.time_s(k) - T.time_s(k - 1)) / p.dt));
    for j = 1:steps
        s = twin_step(s, left(k - 1), right(k - 1), p, w);
    end
    x(k) = s.x; y(k) = s.y; theta(k) = s.theta;
end

robotHeading = T.heading_deg;
if ismember('yaw_deg', T.Properties.VariableNames) && any(~isnan(T.yaw_deg))
    robotHeading = T.yaw_deg - T.yaw_deg(find(~isnan(T.yaw_deg), 1)) + startHeading(T);
end
headingError = wrapDegrees(rad2deg(theta) - robotHeading);
positionError = hypot(x - T.x, y - T.y);
result = struct('folder', sessionFolder, 'headingRmsDeg', sqrt(mean(headingError.^2, 'omitnan')), ...
    'positionRmsM', sqrt(mean(positionError.^2, 'omitnan')));
fprintf('Twin vs robot: heading RMS %.1f deg, position RMS %.1f cm\n', result.headingRmsDeg, 100 * result.positionRmsM);

fig = figure('Name', 'Twin vs robot', 'Color', 'w');
layout = tiledlayout(fig, 2, 1, 'Padding', 'compact');
ax = nexttile(layout);
plot(ax, T.x, T.y, 'DisplayName', 'robot'); hold(ax, 'on');
plot(ax, x, y, '--', 'DisplayName', 'twin');
axis(ax, 'equal'); grid(ax, 'on'); legend(ax); title(ax, 'Path'); xlabel(ax, 'x (m)'); ylabel(ax, 'y (m)');
ax = nexttile(layout);
plot(ax, T.time_s, headingError); grid(ax, 'on');
title(ax, 'Heading difference'); xlabel(ax, 'time (s)'); ylabel(ax, 'degrees');

publish = nargin < 3 || isempty(outputFolder);
if publish, outputFolder = twin_results('new'); end
exportgraphics(fig, fullfile(outputFolder, 'robot_comparison.png'), 'Resolution', 150);
writetable(struct2table(rmfield(result, 'folder')), fullfile(outputFolder, 'robot_comparison.csv'));
if publish, twin_results('publish', outputFolder); end
end

function h = startHeading(T)
h = T.heading_deg(find(~isnan(T.heading_deg), 1));
end

function d = wrapDegrees(d)
d = mod(d + 180, 360) - 180;
end

function folder = newestSession()
root = fullfile(fileparts(mfilename('fullpath')), '..', 'outputs');
files = dir(fullfile(root, '*', 'telemetry.csv'));
if isempty(files)
    error('twin_compare:none', 'No telemetry found. Run the robot first: python main.py start');
end
[~, order] = sort([files.datenum], 'descend');
folder = files(order(1)).folder;
end
