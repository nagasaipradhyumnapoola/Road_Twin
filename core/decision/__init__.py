"""Engineer goal -> decision (P14).

The final layer: an engineer states a measurable goal (reduce travel time /
reduce queue / increase completed vehicles by N %, using at most K
interventions); the search measures the ALREADY-TESTED P13 candidates against
that goal and reports the best tested option that satisfies it — or an honest
"not achieved" with the best result actually reached. No new simulation search
space, no invented numbers, no forced recommendation.
"""
