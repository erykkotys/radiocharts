from radiocharts.metrics import rank_score

def test_rank_score_edges():
    assert rank_score(1,20) == 100
    assert rank_score(20,20) == 0
    assert rank_score(None,20) == 0
    assert rank_score(1,100) > rank_score(50,100) > rank_score(100,100)
