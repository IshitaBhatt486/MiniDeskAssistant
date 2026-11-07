function twin_live(url, seconds, p)
%TWIN_LIVE Run the twin beside the live robot and show where they disagree.
%   twin_live('http://deskbot.local:8000')       until the window is closed
%   twin_live(url, 60)                           for 60 seconds
%   Reads /api/companion/pose (start the robot with: python main.py start --lan).

if nargin < 1 || isempty(url), url = 'http://localhost:8000'; end
if nargin < 2 || isempty(seconds), seconds = inf; end
if nargin < 3, p = twin_params(); end

opts = weboptions('Timeout', 2, 'ContentType', 'json');
endpoint = [strip(url, 'right', '/') '/api/companion/pose'];
first = webread(endpoint, opts);
w = twin_world();
w.circles = zeros(0, 3); w.rects = zeros(0, 4); w.user = zeros(0, 3); w.height = inf;
s = struct('x', first.x, 'y', first.y, 'theta', first.heading, 'vl', 0, 'vr', 0, 'omega', 0);

fig = figure('Name', 'Live digital twin', 'Color', 'w');
ax = axes(fig);
hold(ax, 'on'); axis(ax, 'equal'); grid(ax, 'on');
xlabel(ax, 'x (m)'); ylabel(ax, 'y (m)');
robotLine = animatedline(ax, 'Color', [0.16 0.47 0.84], 'LineWidth', 2, 'DisplayName', 'robot');
twinLine = animatedline(ax, 'Color', [0.92 0.41 0.20], 'LineStyle', '--', 'LineWidth', 1.5, 'DisplayName', 'twin');
legend(ax);

last = first;
history = zeros(0, 7);
started = tic;
while ishandle(fig) && toc(started) < seconds
    pause(0.1);
    try
        sample = webread(endpoint, opts);
    catch
        title(ax, 'Waiting for the robot...');
        continue
    end
    steps = max(1, round((sample.t - last.t) / p.dt));
    for k = 1:min(steps, 100)
        s = twin_step(s, numberOr(last.left), numberOr(last.right), p, w);
    end
    last = sample;
    history(end + 1, :) = [sample.t - first.t, sample.x, sample.y, sample.heading, s.x, s.y, s.theta]; %#ok<AGROW>
    addpoints(robotLine, sample.x, sample.y);
    addpoints(twinLine, s.x, s.y);
    headingGap = rad2deg(atan2(sin(s.theta - sample.heading), cos(s.theta - sample.heading)));
    title(ax, sprintf('Difference: %.1f cm, %.1f deg', 100 * hypot(s.x - sample.x, s.y - sample.y), headingGap));
    drawnow limitrate
end
if ~isempty(history)
    saveSession(history);
end
end

function saveSession(h)
% Saved when the time is up or the window is closed.
folder = twin_results('new');
names = {'time_s', 'robot_x', 'robot_y', 'robot_heading', 'twin_x', 'twin_y', 'twin_heading'};
writetable(array2table(h, 'VariableNames', names), fullfile(folder, 'live_session.csv'));
fig = figure('Visible', 'off', 'Color', 'w');
ax = axes(fig);
plot(ax, h(:, 2), h(:, 3), 'DisplayName', 'robot');
hold(ax, 'on');
plot(ax, h(:, 5), h(:, 6), '--', 'DisplayName', 'twin');
axis(ax, 'equal'); grid(ax, 'on'); legend(ax);
xlabel(ax, 'x (m)'); ylabel(ax, 'y (m)'); title(ax, 'Live session');
exportgraphics(fig, fullfile(folder, 'live_session.png'), 'Resolution', 150);
close(fig);
twin_results('publish', folder);
end

function v = numberOr(x)
if isempty(x), v = 0; else, v = x; end
end
