function twin_animate(log, file, options)
%TWIN_ANIMATE Play a run as a top-down animation and optionally save it.
%   twin_animate(log)                      play in a window
%   twin_animate(log, 'turn.gif')          play and save a GIF (and an MP4 beside it if supported)
%   twin_animate(log, file, struct('fps', 15, 'speed', 1, 'visible', 'off'))
%   Shows the robot, its heading, all four sonar beams, its path, wheel commands and the clock.

if nargin < 2, file = ''; end
if nargin < 3, options = struct(); end
fps = optionOr(options, 'fps', 15);
speed = optionOr(options, 'speed', 1);
visible = optionOr(options, 'visible', 'on');

p = log.params;
fig = figure('Name', ['Animation: ' log.scenario], 'Color', 'w', 'Visible', visible, ...
    'Position', [100 100 760 520], 'PaperPositionMode', 'auto');
cleanup = onCleanup(@() close(fig));
ax = axes(fig);
twin_draw_world(ax, log.world);

trail = plot(ax, log.x(1), log.y(1), 'Color', [0.16 0.47 0.84], 'LineWidth', 1.5);
beams = gobjects(numel(p.sonars), 1);
for k = 1:numel(beams)
    beams(k) = plot(ax, [0 0], [0 0], 'Color', [0.11 0.69 0.48], 'LineWidth', 1);
end
angles = linspace(0, 2 * pi, 40);
body = patch(ax, 'XData', 0, 'YData', 0, 'FaceColor', [0.32 0.32 0.30], 'EdgeColor', 'none');
nose = plot(ax, [0 0], [0 0], 'Color', [0.92 0.41 0.20], 'LineWidth', 3);

stride = max(1, round(speed / (fps * p.dt)));
frames = 1:stride:numel(log.t);
gif = ~isempty(file);
video = [];
if gif
    [folder, name] = fileparts(file);
    video = openVideo(fullfile(folder, [name '.mp4']), fps);
end

for n = 1:numel(frames)
    k = frames(n);
    x = log.x(k); y = log.y(k); th = log.theta(k);
    set(trail, 'XData', log.x(1:k), 'YData', log.y(1:k));
    set(body, 'XData', x + p.bodyRadius * cos(angles), 'YData', y + p.bodyRadius * sin(angles));
    set(nose, 'XData', [x, x + 1.5 * p.bodyRadius * cos(th)], 'YData', [y, y + 1.5 * p.bodyRadius * sin(th)]);
    for b = 1:numel(beams)
        m = p.sonars(b);
        ox = x + m.x * cos(th) - m.y * sin(th);
        oy = y + m.x * sin(th) + m.y * cos(th);
        range = min(log.sonar(k, b), 0.6);        % long beams would hide the desk
        set(beams(b), 'XData', [ox, ox + range * cos(th + m.angle)], 'YData', [oy, oy + range * sin(th + m.angle)]);
    end
    title(ax, sprintf('%s   t = %.1f s   wheels L %+.2f  R %+.2f   %s', strrep(log.scenario, '_', ' '), ...
        log.t(k), log.left(k), log.right(k), stopText(log, k)));
    drawnow limitrate
    if gif
        picture = print(fig, '-RGBImage', '-r96');
        [indexed, map] = rgb2ind(picture, 64);
        if n == 1
            imwrite(indexed, map, file, 'gif', 'LoopCount', inf, 'DelayTime', 1 / fps);
        else
            imwrite(indexed, map, file, 'gif', 'WriteMode', 'append', 'DelayTime', 1 / fps);
        end
        if ~isempty(video)
            writeVideo(video, picture(1:2 * floor(end / 2), 1:2 * floor(size(picture, 2) / 2), :));
        end
    elseif strcmp(visible, 'on')
        pause(1 / fps);
    end
end
if ~isempty(video), close(video); end
end

function label = stopText(log, k)
label = '';
stopped = log.left(k) == 0 && log.right(k) == 0;
if ~isempty(log.stopReason) && stopped && k > 1
    label = ['stopped: ' log.stopReason];
end
end

function value = optionOr(options, name, fallback)
value = fallback;
if isfield(options, name), value = options.(name); end
end

function video = openVideo(file, fps)
% MP4 is not available on every MATLAB platform; the GIF is always written.
video = [];
try
    video = VideoWriter(file, 'MPEG-4');
    video.FrameRate = fps;
    open(video);
catch
    video = [];
end
end
