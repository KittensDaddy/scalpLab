from scalp.runtime import ensure_nofile_limit, fd_stats


def test_fd_stats_shape():
    stats=fd_stats()
    assert "open_fds" in stats
    assert "soft_limit" in stats
    assert stats["state"] in {"OK","WARNING","CRITICAL"}
    if stats["open_fds"] is not None and stats["soft_limit"]:
        assert stats["open_fds"] < stats["soft_limit"]


def test_ensure_nofile_limit_never_lowers():
    before=fd_stats().get("soft_limit")
    result=ensure_nofile_limit(4096)
    after=fd_stats().get("soft_limit")
    assert result["supported"] in {True,False}
    if before and after:
        assert after >= before
