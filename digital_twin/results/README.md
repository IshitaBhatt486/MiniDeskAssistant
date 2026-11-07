# Digital twin results

- `latest/` is a copy of the newest run. It is replaced each time.
- `run_<date>_<time>/` folders are the last 5 runs. Older ones are removed automatically.

A `run_twin` run contains, for each scenario, `<name>_graphs.png`, `<name>_animation.gif`, `<name>_animation.mp4`
(where MATLAB supports MP4) and `<name>_data.csv`, plus `overview.png`, `summary.csv` and, if the robot has saved a run,
`robot_comparison.png` and `robot_comparison.csv`.
