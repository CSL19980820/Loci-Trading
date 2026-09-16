import pandas as pd
import pytest

from scripts.relative_leader_prepare import pullback_shape, relative_values


def test_strength_requires_outperforming_index_and_retaining_advantage():
    stock=pd.Series(10.,index=range(90));index=pd.Series(100.,index=range(90))
    stock.loc[45]=12.;stock.loc[60]=15.;stock.loc[65]=14.7
    index.loc[45]=105.;index.loc[60]=108.;index.loc[65]=109.
    result=relative_values(stock,index,60,65)
    assert result['relative_leader']
    assert result['excess_peak20_pp']==pytest.approx(42.)
    changed=index.copy();changed.loc[60]=155.
    assert not relative_values(stock,changed,60,65)['relative_leader']
    changed=stock.copy();changed.loc[65]=12.
    assert not relative_values(changed,index,60,65)['relative_leader']
    stock.loc[66:]=10000.;index.loc[66:]=100000.
    assert relative_values(stock,index,60,65)==result


def test_pullback_confirmation_never_uses_future_peak():
    f=pd.DataFrame({'open':10.,'high':10.1,'low':9.9,'close':10.,'volume':10_000_000.,'factor':1.},index=range(90))
    for i,row in {70:[12.,13.,11.9,12.9,20_000_000.,1.],71:[12.8,12.9,12.3,12.4,8_000_000.,1.],72:[12.4,12.5,12.,12.1,8_000_000.,1.],73:[12.2,12.8,12.1,12.7,15_000_000.,1.]}.items():f.iloc[i]=row
    _,before=pullback_shape(f)
    assert before.signal.iloc[73]
    f.iloc[74:,0:4]*=100
    _,after=pullback_shape(f)
    pd.testing.assert_frame_equal(before.iloc[:74],after.iloc[:74])
