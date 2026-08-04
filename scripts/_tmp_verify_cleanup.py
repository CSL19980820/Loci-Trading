import sqlite3

con = sqlite3.connect(r"E:\entertainment_software\Loci\data\palace.db")
print("archived left", con.execute(
    """
    SELECT COUNT(*) FROM candidate_reviews
    WHERE decision='精选' AND strategy_slug IN (
      'qianlong-close','qianlong-close-v2','lugw-sanwai','lugw-sanwai-v2','lugw-chouma'
    )
    """
).fetchone()[0])
print("live multi day+code:")
for r in con.execute(
    """
    SELECT occurred_on, code, COUNT(*) n, GROUP_CONCAT(strategy_slug)
    FROM candidate_reviews
    WHERE decision='精选'
      AND IFNULL(source,'') NOT LIKE '%backfill%'
      AND IFNULL(source,'') NOT LIKE '%:history'
      AND occurred_on >= '2026-07-27'
    GROUP BY occurred_on, code
    HAVING n > 1
    """
):
    print(r)
