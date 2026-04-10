"""eclipse-score-baselibs — Dagger pipelines for the eclipse-score/baselibs project.

Upstream: https://github.com/eclipse-score/baselibs
Build system: Bazel 8+ (managed via Bazelisk)
Languages: C++ (94%), Starlark
Dev container: ghcr.io/eclipse-score/devcontainer:1.0.0

All build/test/dev operations run inside the upstream devcontainer image,
pulled through Dagger's content-addressed layer cache via scorenado-shared.
Source is cloned from the upstream public repo using dag.git().
"""

import dagger
from dagger import dag, function, object_type

_UPSTREAM_REPO = "https://github.com/eclipse-score/baselibs"
_DEVCONTAINER_IMAGE = "ghcr.io/eclipse-score/devcontainer:1.0.0"

# Valid Bazel configs for this project
_VALID_CONFIGS = [
    "bl-x86_64-linux",
    "bl-aarch64-linux",
    "bl-x86_64-qnx",
    "bl-aarch64-qnx",
]


def _base(ref: str = "main") -> dagger.Container:
    """Return the devcontainer with the upstream source mounted at /workspace."""
    src = dag.git(_UPSTREAM_REPO).ref(ref).tree()
    return (
        dag.scorenado_shared()
        .containers()
        .from_devcontainer(_DEVCONTAINER_IMAGE)
        .with_mounted_cache(
            "/root/.cache/bazel",
            dag.scorenado_shared().cache().bazel(),
        )
        .with_directory("/workspace", src)
        .with_workdir("/workspace")
    )


@object_type
class EclipseScoreBaselibs:
    """Dagger pipelines for eclipse-score/baselibs."""

    @function
    def build(self) -> "EclipseScoreBaselibsBuild":
        """Return the build sub-object."""
        return EclipseScoreBaselibsBuild()

    @function
    def test(self) -> "EclipseScoreBaselibsTest":
        """Return the test sub-object."""
        return EclipseScoreBaselibsTest()

    @function
    def dev(self) -> "EclipseScoreBaselibsDev":
        """Return the dev sub-object."""
        return EclipseScoreBaselibsDev()


@object_type
class EclipseScoreBaselibsBuild:
    """Build functions for eclipse-score/baselibs."""

    @function
    async def bazel(
        self,
        targets: list[str] = ["//..."],
        config: str = "bl-x86_64-linux",
        ref: str = "main",
    ) -> str:
        """
        Build the specified Bazel targets and return the build log.

        Args:
            targets: Bazel target patterns (default: //...).
            config:  Bazel config flag. One of: bl-x86_64-linux,
                     bl-aarch64-linux, bl-x86_64-qnx, bl-aarch64-qnx.
            ref:     Git ref (branch, tag, or commit SHA) to build.

        Returns the build log (stdout + stderr). Fails the pipeline on
        non-zero exit. Use bazel_artifacts() to extract specific outputs.
        """
        if config not in _VALID_CONFIGS:
            raise ValueError(
                f"Unknown config '{config}'. Valid options: {', '.join(_VALID_CONFIGS)}"
            )
        return await (
            _base(ref)
            .with_exec(
                ["bazel", "build", f"--config={config}"] + targets,
                redirect_stderr=dagger.RedirectMode.STDOUT,
            )
            .stdout()
        )

    @function
    async def bazel_artifacts(
        self,
        artifact_paths: list[str],
        targets: list[str] = ["//..."],
        config: str = "bl-x86_64-linux",
        ref: str = "main",
    ) -> dagger.Directory:
        """
        Build targets and export specific artifact paths from bazel-bin.

        Args:
            artifact_paths: Paths relative to bazel-bin to export
                            (e.g. ["score/utils/libfoo.a", "score/app/mybin"]).
            targets:        Bazel target patterns to build.
            config:         Bazel platform config.
            ref:            Git ref to build.

        Returns a Directory containing only the requested artifacts.
        """
        if config not in _VALID_CONFIGS:
            raise ValueError(
                f"Unknown config '{config}'. Valid options: {', '.join(_VALID_CONFIGS)}"
            )
        # Build a script that copies only the requested paths out of bazel-bin.
        copy_cmds = " && ".join(
            f'mkdir -p /artifacts/$(dirname "{p}") && '
            f'cp -L "$(bazel info bazel-bin)/{p}" "/artifacts/{p}"'
            for p in artifact_paths
        )
        return await (
            _base(ref)
            .with_exec(["bazel", "build", f"--config={config}"] + targets)
            .with_exec(["bash", "-c", copy_cmds])
            .with_exec(["chmod", "-R", "u+rwX", "/artifacts"])
            .directory("/artifacts")
        )

    @function
    async def docs(self, ref: str = "main") -> dagger.Directory:
        """
        Build the Sphinx documentation via `bazel run //:docs`.

        Returns the docs output directory.
        """
        return await (
            _base(ref)
            .with_exec(["bazel", "run", "//:docs"])
            .with_exec(
                ["bash", "-c",
                 "cp -rL $(bazel info bazel-bin) /artifacts && chmod -R u+rwX /artifacts"]
            )
            .directory("/artifacts")
        )


@object_type
class EclipseScoreBaselibsTest:
    """Test functions for eclipse-score/baselibs."""

    @function
    async def all(
        self,
        config: str = "bl-x86_64-linux",
        ref: str = "main",
        sanitizers: bool = False,
    ) -> str:
        """
        Run all Bazel tests.

        Args:
            config:     Bazel config flag (default: bl-x86_64-linux).
            ref:        Git ref to test.
            sanitizers: If True, also apply --config=asan_ubsan_lsan.
        """
        if config not in _VALID_CONFIGS:
            raise ValueError(
                f"Unknown config '{config}'. Valid options: {', '.join(_VALID_CONFIGS)}"
            )
        cmd = ["bazel", "test", f"--config={config}"]
        if sanitizers:
            cmd += ["--config=asan_ubsan_lsan", "--build_tests_only"]
        cmd += ["--", "//score/..."]
        return await _base(ref).with_exec(cmd).stdout()

    @function
    async def unit(
        self,
        config: str = "bl-x86_64-linux",
        ref: str = "main",
    ) -> str:
        """Run Bazel tests tagged as unit tests."""
        if config not in _VALID_CONFIGS:
            raise ValueError(
                f"Unknown config '{config}'. Valid options: {', '.join(_VALID_CONFIGS)}"
            )
        return await (
            _base(ref)
            .with_exec(
                [
                    "bazel", "test", f"--config={config}",
                    "--test_tag_filters=unit",
                    "--", "//score/...",
                ]
            )
            .stdout()
        )


@object_type
class EclipseScoreBaselibsDev:
    """Dev-environment functions for eclipse-score/baselibs."""

    @function
    def shell(self, ref: str = "main") -> dagger.Container:
        """
        Return an interactive dev container with the source mounted and
        the full devcontainer toolchain available.

        The caller (CLI wrapper) is responsible for exporting and running
        this container with `docker run -it --rm`.
        """
        return _base(ref).with_entrypoint(["bash"])
