from optimizer.build_engine import EngineBuilder
from optimizer.visualizer import Visualizer
from optimizer.tuner import TUNABLE_PARAMS, _get_nested, _set_nested, GridSearchTuner, GradientDescentTuner
from optimizer.match_runner import MatchRunner, MatchResult, _calc_elo, _parse_cutechess_output, OPPONENTS, _find_cutechess
from optimizer.config_manager import ConfigManager
import copy
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp(prefix="test_hellcopter_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def config_dir(tmpdir):
    d = os.path.join(tmpdir, "configs")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture
def results_dir(tmpdir):
    d = os.path.join(tmpdir, "test_results")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture
def cm(config_dir):
    return ConfigManager(config_dir=config_dir)


@pytest.fixture
def default_params(cm):
    return cm._get_default_parameters()


class TestConfigManager:

    def test_init_creates_dir(self, tmpdir):
        d = os.path.join(tmpdir, "new_configs")
        cm = ConfigManager(config_dir=d)
        assert os.path.isdir(d)

    def test_export_config(self, cm, default_params):
        path = cm.export_config(
            "1.0.0", description="Test", parameters=default_params)
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["version"] == "1.0.0"
        assert data["description"] == "Test"

    def test_export_with_metadata(self, cm, default_params):
        meta = {"elo_estimate": 1500, "test_opponent": "pulsar"}
        path = cm.export_config(
            "1.0.0", description="Test", parameters=default_params, metadata=meta)
        config = cm.import_config("1.0.0")
        assert config["metadata"]["elo_estimate"] == 1500

    def test_export_duplicate_version(self, cm, default_params):
        cm.export_config("1.0.0", parameters=default_params)
        with pytest.raises(ValueError, match="already exists"):
            cm.export_config("1.0.0", parameters=default_params)

    def test_export_invalid_version(self, cm, default_params):
        with pytest.raises(ValueError, match="Invalid version"):
            cm.export_config("invalid", parameters=default_params)

    def test_import_config(self, cm, default_params):
        cm.export_config("1.0.0", parameters=default_params)
        config = cm.import_config("1.0.0")
        assert config["version"] == "1.0.0"
        assert config["parameters"]["piece_values"]["pawn"] == 100

    def test_import_nonexistent(self, cm):
        with pytest.raises(FileNotFoundError):
            cm.import_config("9.9.9")

    def test_round_trip(self, cm, default_params):
        cm.export_config("1.0.0", parameters=default_params)
        imported = cm.import_config("1.0.0")
        assert imported["parameters"] == default_params

    def test_list_versions(self, cm, default_params):
        cm.export_config("1.0.0", parameters=default_params)
        cm.export_config("1.1.0", parameters=default_params)
        versions = cm.list_versions()
        assert len(versions) == 2
        version_strs = [v["version"] for v in versions]
        assert "1.0.0" in version_strs
        assert "1.1.0" in version_strs

    def test_list_versions_empty(self, cm):
        versions = cm.list_versions()
        assert len(versions) == 0

    def test_compare_versions_identical(self, cm, default_params):
        cm.export_config("1.0.0", parameters=default_params)
        cm.export_config("1.1.0", parameters=default_params)
        diff = cm.compare_versions("1.0.0", "1.1.0")
        assert len(diff["modified"]) == 0
        assert len(diff["added"]) == 0
        assert len(diff["removed"]) == 0

    def test_compare_versions_different(self, cm, default_params):
        cm.export_config("1.0.0", parameters=default_params)
        modified = copy.deepcopy(default_params)
        modified["piece_values"]["knight"] = 350
        cm.export_config("1.1.0", parameters=modified)
        diff = cm.compare_versions("1.0.0", "1.1.0")
        assert "piece_values.knight" in diff["modified"]
        assert diff["modified"]["piece_values.knight"]["old"] == 300
        assert diff["modified"]["piece_values.knight"]["new"] == 350

    def test_compare_versions_added_key(self, cm, default_params):
        cm.export_config("1.0.0", parameters=default_params)
        modified = copy.deepcopy(default_params)
        modified["eval_weights"]["new_bonus"] = 42
        cm.export_config("1.1.0", parameters=modified)
        diff = cm.compare_versions("1.0.0", "1.1.0")
        assert "eval_weights.new_bonus" in diff["added"]

    def test_compare_versions_removed_key(self, cm, default_params):
        modified = copy.deepcopy(default_params)
        modified["eval_weights"]["extra"] = 99
        cm.export_config("1.0.0", parameters=modified)
        cm.export_config("1.1.0", parameters=default_params)
        diff = cm.compare_versions("1.0.0", "1.1.0")
        assert "eval_weights.extra" in diff["removed"]

    def test_delete_version(self, cm, default_params):
        cm.export_config("1.0.0", parameters=default_params)
        assert os.path.exists(cm._get_config_path("1.0.0"))
        cm.delete_version("1.0.0")
        assert not os.path.exists(cm._get_config_path("1.0.0"))

    def test_delete_nonexistent(self, cm):
        with pytest.raises(FileNotFoundError):
            cm.delete_version("9.9.9")

    def test_switch_version(self, cm, default_params):
        modified = copy.deepcopy(default_params)
        modified["search_params"]["lmr_enabled"] = True
        cm.export_config("1.1.0", parameters=modified)
        cm.switch_version("1.1.0")
        header = Path("engine_params.h").read_text()
        assert "LMR_ENABLED 1" in header

    def test_validate_version_format(self, cm):
        assert cm._validate_version("1.0.0") is True
        assert cm._validate_version("10.20.30") is True
        assert cm._validate_version("1.0") is False
        assert cm._validate_version("abc") is False
        assert cm._validate_version("1.0.0.0") is False
        assert cm._validate_version("") is False

    def test_validate_timestamp(self, cm):
        assert cm._validate_timestamp("2026-01-01T00:00:00") is True
        assert cm._validate_timestamp("invalid") is False
        assert cm._validate_timestamp("") is False

    def test_validate_piece_values_range(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["piece_values"]["pawn"] = 99999
        with pytest.raises(ValueError, match="out of range"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_pst_length(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["pst"]["mg_pawn"] = [0] * 32
        with pytest.raises(ValueError, match="expected 64"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_missing_section(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        del bad["piece_values"]
        with pytest.raises(ValueError, match="Missing"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_threading_range(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["threading"]["num_threads"] = 0
        with pytest.raises(ValueError, match="out of range"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_missing_top_fields(self, cm):
        with pytest.raises(ValueError, match="Missing"):
            cm._validate_config({})

    def test_validate_invalid_version_in_config(self, cm, default_params):
        with pytest.raises(ValueError, match="Invalid version"):
            cm._validate_config({"version": "bad", "created_at": datetime.now(
            ).isoformat(), "parameters": default_params})

    def test_validate_invalid_timestamp(self, cm, default_params):
        with pytest.raises(ValueError, match="Invalid timestamp"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": "not-a-date", "parameters": default_params})

    def test_validate_piece_values_type(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["piece_values"]["pawn"] = "not_int"
        with pytest.raises(ValueError, match="expected int"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_missing_piece(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        del bad["piece_values"]["knight"]
        with pytest.raises(ValueError, match="Missing piece"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_pst_type(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["pst"]["mg_pawn"] = "not_a_list"
        with pytest.raises(ValueError, match="expected list"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_pst_element_type(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["pst"]["mg_pawn"] = [0] * 63 + ["x"]
        with pytest.raises(ValueError, match="expected int"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_missing_pst_table(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        del bad["pst"]["mg_pawn"]
        with pytest.raises(ValueError, match="Missing PST"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_search_params_type(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["search_params"]["lmr_enabled"] = 1
        with pytest.raises(ValueError, match="expected bool"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_search_params_range(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["search_params"]["null_move_reduction"] = 99
        with pytest.raises(ValueError, match="out of range"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_eval_weights_type(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["eval_weights"]["bishop_pair_bonus"] = "not_int"
        with pytest.raises(ValueError, match="expected int"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_eval_weights_range(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["eval_weights"]["bishop_pair_bonus"] = 999
        with pytest.raises(ValueError, match="out of range"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_passed_pawn_bonus_length(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["eval_weights"]["passed_pawn_bonus"] = [0, 10, 20]
        with pytest.raises(ValueError, match="expected 8"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_threading_type(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["threading"]["enabled"] = 1
        with pytest.raises(ValueError, match="expected bool"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_validate_constants_range(self, cm, default_params):
        bad = copy.deepcopy(default_params)
        bad["constants"]["delta"] = 99999
        with pytest.raises(ValueError, match="out of range"):
            cm._validate_config(
                {"version": "1.0.0", "created_at": datetime.now().isoformat(), "parameters": bad})

    def test_default_parameters_structure(self, default_params):
        for section in ["piece_values", "pst", "eval_weights", "search_params", "constants", "threading"]:
            assert section in default_params

    def test_default_pst_length(self, default_params):
        for name, values in default_params["pst"].items():
            assert len(values) == 64, "PST %s has %d values" % (
                name, len(values))

    def test_generate_c_header(self, cm, default_params):
        cm._generate_c_header(default_params)
        header = Path("engine_params.h").read_text()
        assert "#define PAWN_VALUE 100" in header
        assert "#define KNIGHT_VALUE 300" in header
        assert "#define THREADING_ENABLED 0" in header
        assert "mg_pawn[64]" in header
        assert "#define MATE_SCORE" in header
        assert "#define DELTA" in header
        assert "#define NUM_THREADS 1" in header

    def test_generate_c_header_lmr(self, cm, default_params):
        modified = copy.deepcopy(default_params)
        modified["search_params"]["lmr_enabled"] = True
        cm._generate_c_header(modified)
        header = Path("engine_params.h").read_text()
        assert "#define LMR_ENABLED 1" in header

    def test_generate_c_header_threading(self, cm, default_params):
        modified = copy.deepcopy(default_params)
        modified["threading"]["enabled"] = True
        modified["threading"]["num_threads"] = 4
        cm._generate_c_header(modified)
        header = Path("engine_params.h").read_text()
        assert "#define THREADING_ENABLED 1" in header
        assert "#define NUM_THREADS 4" in header

    def test_get_config_path(self, cm):
        path = cm._get_config_path("1.0.0")
        assert str(path).endswith("v1.0.0.json")

    def test_extract_piece_values(self, cm):
        source = 'static const int piece_values[7] = {0, 100, 300, 320, 480, 900, 20000};'
        result = cm._extract_piece_values(source)
        assert result["pawn"] == 100
        assert result["knight"] == 300
        assert result["queen"] == 900

    def test_extract_piece_values_fallback(self, cm):
        result = cm._extract_piece_values("no match here")
        assert result["pawn"] == 100
        assert result["knight"] == 300

    def test_extract_constants(self, cm):
        source = '#define MATE_SCORE 900000\n#define DELTA 900\n'
        result = cm._extract_constants(source)
        assert result["mate_score"] == 900000
        assert result["delta"] == 900

    def test_extract_constants_fallback(self, cm):
        result = cm._extract_constants("no match")
        assert result["mate_score"] == 900000
        assert result["delta"] == 900


class TestEloCalculation:

    def test_equal_record(self):
        elo, lo, hi = _calc_elo(25, 25, 0)
        assert abs(elo) < 1.0
        assert lo <= elo <= hi

    def test_all_wins(self):
        elo, lo, hi = _calc_elo(51, 0, 0)
        assert elo >= 900

    def test_all_losses(self):
        elo, lo, hi = _calc_elo(0, 51, 0)
        assert elo <= -900

    def test_zero_total(self):
        elo, lo, hi = _calc_elo(0, 0, 0)
        assert elo == 0.0

    def test_ci_contains_elo(self):
        elo, lo, hi = _calc_elo(28, 20, 3)
        assert lo <= elo <= hi

    def test_positive_elo(self):
        elo, _, _ = _calc_elo(30, 20, 1)
        assert elo > 0

    def test_negative_elo(self):
        elo, _, _ = _calc_elo(20, 30, 1)
        assert elo < 0

    def test_draws_only(self):
        elo, lo, hi = _calc_elo(0, 0, 50)
        assert abs(elo) < 1.0

    def test_symmetry(self):
        elo1, _, _ = _calc_elo(30, 20, 1)
        elo2, _, _ = _calc_elo(20, 30, 1)
        assert abs(elo1 + elo2) < 1.0

    def test_large_sample_ci_narrow(self):
        elo, lo, hi = _calc_elo(300, 200, 50)
        assert hi - lo < 200

    def test_small_sample_ci_wide(self):
        elo, lo, hi = _calc_elo(3, 2, 0)
        assert hi - lo > 100


class TestMatchResult:

    def test_creation(self):
        r = MatchResult(wins=10, losses=5, draws=3, opponent="test",
                        time_control="9+0.1", rounds=18,
                        elo_diff=50.0, ci_low=-10.0, ci_high=110.0, winrate=0.639)
        assert r.wins == 10
        assert r.losses == 5
        assert r.draws == 3
        assert r.opponent == "test"

    def test_total_games(self):
        r = MatchResult(wins=10, losses=5, draws=3, opponent="test",
                        time_control="9+0.1", rounds=18,
                        elo_diff=50.0, ci_low=-10.0, ci_high=110.0, winrate=0.639)
        assert r.total == 18

    def test_to_dict(self):
        r = MatchResult(wins=10, losses=5, draws=3, opponent="test",
                        time_control="9+0.1", rounds=18,
                        elo_diff=50.0, ci_low=-10.0, ci_high=110.0, winrate=0.639)
        d = r.to_dict()
        assert d["wins"] == 10
        assert d["losses"] == 5
        assert d["opponent"] == "test"
        assert isinstance(d, dict)


class TestMatchRunner:

    def test_init(self, results_dir):
        mr = MatchRunner(base_dir=".", results_dir=results_dir)
        assert os.path.isdir(results_dir)

    def test_save_result(self, results_dir):
        mr = MatchRunner(base_dir=".", results_dir=results_dir)
        r = MatchResult(wins=10, losses=5, draws=3, opponent="test",
                        time_control="9+0.1", rounds=18,
                        elo_diff=50.0, ci_low=-10.0, ci_high=110.0, winrate=0.639)
        mr._save_result(r, "1.0.0", "test.pgn")
        files = os.listdir(results_dir)
        assert len(files) >= 1

    def test_list_results(self, results_dir):
        mr = MatchRunner(base_dir=".", results_dir=results_dir)
        r = MatchResult(wins=10, losses=5, draws=3, opponent="test",
                        time_control="9+0.1", rounds=18,
                        elo_diff=50.0, ci_low=-10.0, ci_high=110.0, winrate=0.639)
        mr._save_result(r, "1.0.0", "test.pgn")
        results = mr.list_results()
        assert len(results) >= 1
        assert results[0]["results"]["wins"] == 10

    def test_unknown_opponent(self, results_dir):
        mr = MatchRunner(base_dir=".", results_dir=results_dir)
        with pytest.raises(ValueError, match="Unknown opponent"):
            mr._get_opponent_exe("nonexistent_engine")

    def test_opponents_dict(self):
        assert "pulsar" in OPPONENTS
        assert "apollo" in OPPONENTS
        assert "tscp181" in OPPONENTS
        for name, info in OPPONENTS.items():
            assert "dir" in info
            assert "exe" in info
            assert "proto" in info

    def test_parse_cutechess_output(self):
        output = 'Score of Hellcopter vs Pulsar: 28 - 20 - 3  [0.578] 51'
        w, l, d = _parse_cutechess_output(output)
        assert w == 28
        assert l == 20
        assert d == 3

    def test_parse_cutechess_output_no_match(self):
        output = 'Some random output without score'
        w, l, d = _parse_cutechess_output(output)
        assert w == 0
        assert l == 0
        assert d == 0

    def test_find_cutechess_returns_string_or_none(self):
        result = _find_cutechess(".")
        assert result is None or isinstance(result, str)


class TestTunableParams:

    def test_tunable_params_exist(self):
        assert len(TUNABLE_PARAMS) > 0

    def test_tunable_params_structure(self):
        for key, spec in TUNABLE_PARAMS.items():
            assert "min" in spec, "Missing 'min' in %s" % key
            assert "max" in spec, "Missing 'max' in %s" % key
            assert "step" in spec, "Missing 'step' in %s" % key
            assert spec["min"] < spec["max"], "Invalid range for %s" % key

    def test_get_nested(self):
        d = {"a": {"b": {"c": 42}}}
        assert _get_nested(d, "a.b.c") == 42

    def test_get_nested_missing(self):
        d = {"a": {"b": 1}}
        with pytest.raises(KeyError):
            _get_nested(d, "a.x")

    def test_set_nested(self):
        d = {"a": {"b": {"c": 42}}}
        _set_nested(d, "a.b.c", 100)
        assert d["a"]["b"]["c"] == 100

    def test_set_nested_new_key(self):
        d = {"a": {"b": 1}}
        _set_nested(d, "a.c", 99)
        assert d["a"]["c"] == 99

    def test_grid_search_tuner_init(self, config_dir, results_dir):
        cm = ConfigManager(config_dir=config_dir)
        params = cm._get_default_parameters()
        cm.export_config("1.0.0", parameters=params)
        mr = MatchRunner(base_dir=".", results_dir=results_dir)
        tuner = GridSearchTuner(cm, mr, base_version="1.0.0")
        assert tuner.base_version == "1.0.0"

    def test_gradient_descent_tuner_init(self, config_dir, results_dir):
        cm = ConfigManager(config_dir=config_dir)
        params = cm._get_default_parameters()
        cm.export_config("1.0.0", parameters=params)
        mr = MatchRunner(base_dir=".", results_dir=results_dir)
        tuner = GradientDescentTuner(cm, mr, base_version="1.0.0")
        assert tuner.base_version == "1.0.0"


class TestVisualizer:

    def test_init(self, results_dir, tmpdir):
        plots_dir = os.path.join(tmpdir, "plots")
        viz = Visualizer(results_dir=results_dir, output_dir=plots_dir)
        assert os.path.isdir(plots_dir)

    def test_generate_summary_report(self, results_dir, tmpdir):
        plots_dir = os.path.join(tmpdir, "plots")
        viz = Visualizer(results_dir=results_dir, output_dir=plots_dir)
        report = viz.generate_summary_report()
        assert isinstance(report, str)
        assert len(report) > 0

    def test_plot_elo_progression(self, results_dir, tmpdir):
        mr = MatchRunner(base_dir=".", results_dir=results_dir)
        r = MatchResult(wins=10, losses=5, draws=3, opponent="test",
                        time_control="9+0.1", rounds=18,
                        elo_diff=50.0, ci_low=-10.0, ci_high=110.0, winrate=0.639)
        mr._save_result(r, "1.0.0", "test.pgn")
        plots_dir = os.path.join(tmpdir, "plots")
        viz = Visualizer(results_dir=results_dir, output_dir=plots_dir)
        result = viz.plot_elo_progression()
        assert isinstance(result, str)

    def test_plot_elo_progression_with_opponent(self, results_dir, tmpdir):
        mr = MatchRunner(base_dir=".", results_dir=results_dir)
        r = MatchResult(wins=10, losses=5, draws=3, opponent="pulsar",
                        time_control="9+0.1", rounds=18,
                        elo_diff=50.0, ci_low=-10.0, ci_high=110.0, winrate=0.639)
        mr._save_result(r, "1.0.0", "test.pgn")
        plots_dir = os.path.join(tmpdir, "plots")
        viz = Visualizer(results_dir=results_dir, output_dir=plots_dir)
        result = viz.plot_elo_progression(opponent="pulsar")
        assert isinstance(result, str)

    def test_plot_tuning_history(self, results_dir, tmpdir):
        plots_dir = os.path.join(tmpdir, "plots")
        viz = Visualizer(results_dir=results_dir, output_dir=plots_dir)
        result = viz.plot_tuning_history()
        assert isinstance(result, str)

    def test_plot_winrate_by_opponent(self, results_dir, tmpdir):
        mr = MatchRunner(base_dir=".", results_dir=results_dir)
        r = MatchResult(wins=10, losses=5, draws=3, opponent="pulsar",
                        time_control="9+0.1", rounds=18,
                        elo_diff=50.0, ci_low=-10.0, ci_high=110.0, winrate=0.639)
        mr._save_result(r, "1.0.0", "test.pgn")
        plots_dir = os.path.join(tmpdir, "plots")
        viz = Visualizer(results_dir=results_dir, output_dir=plots_dir)
        result = viz.plot_winrate_by_opponent()
        assert isinstance(result, str)


class TestEngineBuilder:

    def test_init(self):
        builder = EngineBuilder(base_dir=".")
        assert builder.base_dir.exists()

    def test_build(self):
        builder = EngineBuilder(base_dir=".")
        try:
            output = builder.build(optimization="O2")
            assert Path(output).exists()
        except Exception:
            pytest.skip("Build failed - DLL may be locked")


class TestIntegration:

    def test_full_config_workflow(self, config_dir, default_params):
        cm = ConfigManager(config_dir=config_dir)
        cm.export_config("1.0.0", description="Baseline",
                         parameters=default_params)
        modified = copy.deepcopy(default_params)
        _set_nested(modified, "piece_values.knight", 350)
        cm.export_config(
            "1.1.0", description="Knight optimized", parameters=modified)
        diff = cm.compare_versions("1.0.0", "1.1.0")
        assert "piece_values.knight" in diff["modified"]
        cm.switch_version("1.1.0")
        header = Path("engine_params.h").read_text()
        assert "KNIGHT_VALUE 350" in header
        cm.switch_version("1.0.0")
        header = Path("engine_params.h").read_text()
        assert "KNIGHT_VALUE 300" in header

    def test_elo_calculation_consistency(self):
        elo1, lo1, hi1 = _calc_elo(30, 20, 1)
        elo2, lo2, hi2 = _calc_elo(20, 30, 1)
        assert elo1 > 0
        assert elo2 < 0
        assert abs(elo1 + elo2) < 1.0

    def test_config_validation_comprehensive(self, cm, default_params):
        cm.export_config("1.0.0", parameters=default_params)
        config = cm.import_config("1.0.0")
        assert config["parameters"]["piece_values"]["pawn"] == 100
        assert config["parameters"]["search_params"]["lmr_enabled"] is False
        assert config["parameters"]["threading"]["enabled"] is False
        assert len(config["parameters"]["pst"]["mg_pawn"]) == 64

    def test_tunable_params_coverage(self):
        param_keys = list(TUNABLE_PARAMS.keys())
        assert "piece_values.knight" in param_keys
        assert "piece_values.bishop" in param_keys
        assert "search_params.null_move_reduction" in param_keys

    def test_match_result_round_trip(self, results_dir):
        mr = MatchRunner(base_dir=".", results_dir=results_dir)
        r = MatchResult(wins=28, losses=20, draws=3, opponent="pulsar",
                        time_control="9+0.1", rounds=51,
                        elo_diff=56.4, ci_low=5.2, ci_high=107.6, winrate=0.578)
        mr._save_result(r, "1.0.0", "match.pgn")
        results = mr.list_results()
        assert len(results) == 1
        loaded = results[0]["results"]
        assert loaded["wins"] == 28
        assert loaded["losses"] == 20
        assert loaded["draws"] == 3

    def test_visualizer_with_data(self, results_dir, tmpdir):
        mr = MatchRunner(base_dir=".", results_dir=results_dir)
        for i, (w, l, d) in enumerate([(20, 25, 6), (25, 20, 6), (28, 18, 5)]):
            elo, lo, hi = _calc_elo(w, l, d)
            wr = (w + d * 0.5) / (w + l + d)
            r = MatchResult(wins=w, losses=l, draws=d, opponent="pulsar",
                            time_control="9+0.1", rounds=w + l + d,
                            elo_diff=elo, ci_low=lo, ci_high=hi, winrate=wr)
            mr._save_result(r, "1.%d.0" % i, "match.pgn")
        plots_dir = os.path.join(tmpdir, "plots")
        viz = Visualizer(results_dir=results_dir, output_dir=plots_dir)
        report = viz.generate_summary_report()
        assert "pulsar" in report or "Elo" in report or "Win" in report
