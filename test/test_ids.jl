let
    geom = LazySets.Ball2(zeros(SVector{3,Float64}), 1.0)
    o = ConstructionBots.ObjectNode(ConstructionBots.ObjectID(1), ConstructionBots.GeomNode(deepcopy(geom)))
    r = ConstructionBots.RobotNode(ConstructionBots.RobotID(1), ConstructionBots.GeomNode(deepcopy(geom)))
    a = ConstructionBots.AssemblyNode(ConstructionBots.AssemblyID(1), ConstructionBots.GeomNode(deepcopy(geom)))
    t = ConstructionBots.TransportUnitNode(ConstructionBots.node_id(a))

    predicates = [
        ConstructionBots.ObjectStart(o),
        ConstructionBots.RobotStart(r),
        ConstructionBots.RobotGo(r),
        ConstructionBots.AssemblyStart(a),
        ConstructionBots.AssemblyComplete(a),
        ConstructionBots.LiftIntoPlace(a),
        ConstructionBots.LiftIntoPlace(o),
        ConstructionBots.FormTransportUnit(t),
        ConstructionBots.TransportUnitGo(t),
        ConstructionBots.DepositCargo(t),
    ]
    s = Set{ConstructionBots.AbstractID}(ConstructionBots.node_id(n) for n in predicates)
    @test length(s) == length(predicates) # every predicate has an ID of its own, even with the same number

    # The hash must not depend on the build: it is a function of the type's name and the number only.
    id = ConstructionBots.ObjectID(3)
    @test hash(id) == hash(3, xor(hash("ObjectID"), zero(UInt)))
    @test hash(id) == hash(ConstructionBots.ObjectID(3))
    @test hash(id) != hash(ConstructionBots.ObjectID(4))
    @test hash(id) != hash(ConstructionBots.AssemblyID(3))
    @test ConstructionBots.stable_id_key(id) == ("ObjectID", 3)
    @test length(unique(hash(ConstructionBots.node_id(n)) for n in predicates)) == length(predicates)

    # Strictly increasing, even within one tick of the clock: equal stamps made the scene tree recurse forever.
    stamps = [ConstructionBots.next_time_stamp() for _ in 1:100_000]
    @test all(diff(stamps) .> 0)
    @test abs(stamps[end] - time()) < 60 # still wall-clock seconds
end
