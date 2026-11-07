function folder = twin_results(action, folder, keep)
%TWIN_RESULTS Manage the digital_twin/results folder.
%   folder = twin_results('new')            create results/run_<date>_<time>
%   twin_results('publish', folder)         make results/latest a copy of that run
%   twin_results('new', [], keep)           keep this many runs (default 5)
%   Only folders named run_<date>_<time> are ever removed, oldest first.

root = fullfile(fileparts(mfilename('fullpath')), 'results');
if nargin < 3 || isempty(keep), keep = 5; end
switch action
    case 'new'
        if ~isfolder(root), mkdir(root); end
        stamp = char(datetime('now', 'Format', 'yyyyMMdd_HHmmss'));
        folder = fullfile(root, ['run_' stamp]);
        if ~isfolder(folder), mkdir(folder); end
        prune(root, keep);
    case 'publish'
        latest = fullfile(root, 'latest');
        if isfolder(latest), rmdir(latest, 's'); end
        copyfile(folder, latest);
        fprintf('Results saved in %s\n', latest);
    otherwise
        error('twin_results:action', 'Unknown action: %s', action);
end
end

function prune(root, keep)
items = dir(fullfile(root, 'run_*'));
names = {items([items.isdir]).name};
names = sort(names(~cellfun(@isempty, regexp(names, '^run_\d{8}_\d{6}$', 'once'))));
for k = 1:numel(names) - keep
    rmdir(fullfile(root, names{k}), 's');
end
end
