#include "mosaic/mission.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace mm=mosaic::mission;
void check(bool condition, const char* message) {if (!condition) throw std::runtime_error(message);}
int main() {
    // Off-grid endpoints exposed a stale-queue bug; every returned segment
    // must clear the expanded obstacle, including grid endpoint connectors.
    const std::vector<mm::Box> obstacles{{3,0,1,6},{6,4,1,6}};
    const auto path=mm::plan_path({1.13,1.17},{8.83,8.87},{0,0},{10,10},obstacles,.3,.4);
    check(path.size()>2,"detour not found");
    for (std::size_t i=1;i<path.size();++i) check(mm::clear_segment(path[i-1],path[i],obstacles,.4),"path intersects wall");
    check(mm::plan_path({1,1},{9,9},{0,0},{10,10},{{4,0,2,10}},.3,.4).empty(),"sealed wall crossed");
    // Captured from a real return flight: the aircraft clears the inflated
    // wall, but its nearest grid point (10.5,4.75) is inside that wall.
    const std::vector<mm::Box> doorway{{3,4,7,.25},{12,4.25,.2,3.75}};
    for (const auto reverse:{false,true}) {
        const mm::Point near_wall{10.55,4.85},dock{7,1.8};
        const auto recovered=mm::plan_path(reverse?dock:near_wall,reverse?near_wall:dock,
                                          {0,0},{26,19},doorway,.25,.58);
        check(recovered.size()>2,"off-grid doorway connector not found");
        for (std::size_t i=1;i<recovered.size();++i)
            check(mm::clear_segment(recovered[i-1],recovered[i],doorway,.58),"connector reduced clearance");
    }
    const std::vector<mm::Box> discovered{{17,9.8,.4,.4}};
    const mm::Point trapped{17.66,9.39};
    check(mm::plan_path(trapped,{21.5,15},{0,0},{26,19},discovered,.25,.58).empty(),
          "strict preferred margin silently reduced");
    const auto escape=mm::plan_path(trapped,{21.5,15},{0,0},{26,19},discovered,.25,.58,.35);
    check(escape.size()>=3,"safe local exit unavailable");
    check(std::hypot(escape[1].x-trapped.x,escape[1].y-trapped.y)<=1,"exit exceeds local bound");
    check(mm::clear_segment(escape[0],escape[1],discovered,.35),"exit violates body margin");
    for (std::size_t i=2;i<escape.size();++i)
        check(mm::clear_segment(escape[i-1],escape[i],discovered,.58),"route after exit reduces preferred margin");
    check(mm::plan_path({17.2,9.7},{21.5,15},{0,0},{26,19},discovered,.25,.58,.35).empty(),
          "unsafe start allowed to cross obstacle");
    std::vector<mm::Range> ranges;
    const mm::Point person{4.3,7.8};
    const std::vector<mm::Point> anchors{{0,0},{10,0},{0,12},{10,12},{5,-3}};
    for (std::size_t i=0;i<anchors.size();++i) {
        const auto a=anchors[i];
        const auto range=std::sqrt((a.x-person.x)*(a.x-person.x)+(a.y-person.y)*(a.y-person.y)+.36);
        ranges.push_back({std::to_string(i),a.x,a.y,.5,range+(i==4?3.0:0),.06});
    }
    const auto estimate=mm::locate(ranges,1.1);
    check(estimate.has_value(),"robust fix unavailable");
    check(std::hypot(estimate->position.x-person.x,estimate->position.y-person.y)<.01,"outlier corrupted fix");
    check(estimate->rejected==std::vector<std::string>{"4"},"outlier not excluded");
    ranges[1].id=ranges[0].id;
    check(!mm::locate(ranges,1.1),"duplicate identity accepted");
    check(!mm::locate({{"a",0,0,0,3,.1},{"b",1,0,0,2,.1}},1.1),"two anchors produced fix");
    std::cout<<"mission core: paths, collision margins, NLOS exclusion and identity checks passed\n";
}
