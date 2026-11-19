#include "mosaic/mission.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <queue>
#include <set>
#include <stdexcept>
#include <tuple>

namespace mosaic::mission {
namespace {
void require(bool value, const char* error) { if (!value) throw std::invalid_argument(error); }
double number(const Json& j, double low, double high) {
    require(j.is_number(), "number_required");
    const auto value=j.get<double>();
    require(std::isfinite(value) && value>=low && value<=high, "number_out_of_range");
    return value;
}
Point point(const Json& j) { return {number(j.at(0),-1000,1000),number(j.at(1),-1000,1000)}; }
double distance(Point a, Point b) { return std::hypot(a.x-b.x,a.y-b.y); }
bool inside(Point p, const Box& b, double c) {
    return p.x>=b.x-c && p.x<=b.x+b.width+c && p.y>=b.y-c && p.y<=b.y+b.height+c;
}
bool intersects(Point a, Point b, const Box& box, double c) {
    double begin=0, end=1;
    const std::array<double,2> origin{a.x,a.y}, delta{b.x-a.x,b.y-a.y};
    const std::array<double,2> lower{box.x-c,box.y-c}, upper{box.x+box.width+c,box.y+box.height+c};
    for (std::size_t i=0;i<2;++i) {
        if (std::abs(delta[i])<1e-12) { if (origin[i]<lower[i] || origin[i]>upper[i]) return false; }
        else {
            auto t0=(lower[i]-origin[i])/delta[i], t1=(upper[i]-origin[i])/delta[i];
            if (t0>t1) std::swap(t0,t1);
            begin=std::max(begin,t0); end=std::min(end,t1);
            if (begin>end) return false;
        }
    }
    return true;
}
std::optional<Point> solve(const std::vector<Range>& ranges, const std::vector<std::size_t>& subset,
                           double height, Point start) {
    Point p=start;
    for (int iteration=0;iteration<60;++iteration) {
        double a=0,b=0,d=0,gx=0,gy=0;
        for (auto index:subset) {
            const auto& r=ranges[index];
            const auto dx=p.x-r.x,dy=p.y-r.y,dz=height-r.z;
            const auto predicted=std::sqrt(dx*dx+dy*dy+dz*dz);
            if (predicted<1e-8) continue;
            const auto jx=dx/predicted,jy=dy/predicted,w=1/(r.sigma*r.sigma);
            const auto residual=predicted-r.distance;
            a+=w*jx*jx;b+=w*jx*jy;d+=w*jy*jy;gx+=w*jx*residual;gy+=w*jy*residual;
        }
        const auto determinant=a*d-b*b;
        if (determinant<1e-8*(a+d)*(a+d)) return std::nullopt;
        auto dx=(d*gx-b*gy)/determinant,dy=(a*gy-b*gx)/determinant;
        const auto step=std::hypot(dx,dy);
        if (step>2) { dx*=2/step;dy*=2/step; }
        p.x-=dx;p.y-=dy;
        if (!std::isfinite(p.x) || !std::isfinite(p.y)) return std::nullopt;
        if (step<1e-6) return p;
    }
    return std::nullopt;
}
double residual(Point p, const Range& r, double h) {
    return std::abs(std::hypot(distance(p,{r.x,r.y}),h-r.z)-r.distance);
}
} // namespace

bool clear_segment(Point a, Point b, const std::vector<Box>& obstacles, double clearance) {
    return std::none_of(obstacles.begin(),obstacles.end(),[&](const auto& box){return intersects(a,b,box,clearance);});
}

std::vector<Point> plan_path(Point from, Point to, Point minimum, Point maximum,
                             const std::vector<Box>& obstacles, double cell, double clearance,
                             std::optional<double> escape_clearance) {
    require(std::isfinite(cell) && cell>=.1 && cell<=2, "invalid_grid_resolution");
    require(clearance>=0 && clearance<=3, "invalid_clearance");
    require(!escape_clearance || (*escape_clearance>=0 && *escape_clearance<=clearance),"invalid_escape_clearance");
    require(maximum.x>minimum.x && maximum.y>minimum.y,"invalid_grid_bounds");
    const auto width=static_cast<int>(std::ceil((maximum.x-minimum.x)/cell))+1;
    const auto height=static_cast<int>(std::ceil((maximum.y-minimum.y)/cell))+1;
    require(static_cast<long long>(width)*height<=100000,"grid_capacity");
    auto valid=[&](Point p) {
        return p.x>=minimum.x && p.x<=maximum.x && p.y>=minimum.y && p.y<=maximum.y &&
          std::none_of(obstacles.begin(),obstacles.end(),[&](const auto& b){return inside(p,b,clearance);});
    };
    if (!valid(to)) return {};
    if (!valid(from)) {
        // A controller or newly observed cell can put the aircraft inside the
        // preferred planning margin while its body still has safe clearance.
        // Permit only a short, sensor-checked exit to the ordinary free space;
        // the remainder of the route keeps the original planning margin.
        if (!escape_clearance || from.x<minimum.x || from.x>maximum.x ||
            from.y<minimum.y || from.y>maximum.y ||
            !clear_segment(from,from,obstacles,*escape_clearance)) return {};
        std::vector<Point> exits;
        const auto radius=static_cast<int>(std::ceil(1.0/cell));
        for (int dy=-radius;dy<=radius;++dy) for (int dx=-radius;dx<=radius;++dx) {
            Point p{from.x+dx*cell,from.y+dy*cell};
            if (distance(from,p)<=1.0 && valid(p) && clear_segment(from,p,obstacles,*escape_clearance))
                exits.push_back(p);
        }
        std::sort(exits.begin(),exits.end(),[&](Point a,Point b){
            return distance(from,a)+distance(a,to)<distance(from,b)+distance(b,to);
        });
        for (std::size_t i=0;i<std::min<std::size_t>(8,exits.size());++i) {
            auto route=plan_path(exits[i],to,minimum,maximum,obstacles,cell,clearance);
            if (!route.empty()) {route.insert(route.begin(),from);return route;}
        }
        return {};
    }
    if (clear_segment(from,to,obstacles,clearance)) return {from,to};
    auto coordinate=[&](int i){return Point{minimum.x+(i%width)*cell,minimum.y+(i/width)*cell};};
    // A valid off-grid endpoint can round into an expanded wall. Attach it to
    // the closest visible neighbouring grid point, preserving the same margin
    // on the entire connector instead of declaring a reachable doorway shut.
    auto connector=[&](Point p) {
        const auto cx=static_cast<int>(std::round((p.x-minimum.x)/cell));
        const auto cy=static_cast<int>(std::round((p.y-minimum.y)/cell));
        int best=-1;double nearest=std::numeric_limits<double>::infinity();
        for (int dy=-1;dy<=1;++dy) for (int dx=-1;dx<=1;++dx) {
            const auto x=cx+dx,y=cy+dy;
            if (x<0 || x>=width || y<0 || y>=height) continue;
            const auto candidate=y*width+x;const auto q=coordinate(candidate);
            const auto length=distance(p,q);
            if (length<nearest && valid(q) && clear_segment(p,q,obstacles,clearance)) {
                best=candidate;nearest=length;
            }
        }
        return best;
    };
    const int count=width*height,start=connector(from),goal=connector(to);
    if (start<0 || goal<0) return {};
    std::vector<double> cost(static_cast<std::size_t>(count),std::numeric_limits<double>::infinity());
    std::vector<int> parent(static_cast<std::size_t>(count),-1);
    using Item=std::pair<double,int>;
    std::priority_queue<Item,std::vector<Item>,std::greater<>> open;
    cost[static_cast<std::size_t>(start)]=0;open.emplace(distance(coordinate(start),coordinate(goal)),start);
    const std::array<std::pair<int,int>,8> offsets{{{1,0},{0,1},{-1,0},{0,-1},{1,1},{1,-1},{-1,1},{-1,-1}}};
    while (!open.empty()) {
        const auto [score,current]=open.top();open.pop();
        const auto current_point=coordinate(current);
        if (score>cost[static_cast<std::size_t>(current)]+distance(current_point,coordinate(goal))+1e-8) continue;
        if (current==goal) break;
        for (const auto& [dx,dy]:offsets) {
            const auto x=current%width+dx,y=current/width+dy;
            if (x<0 || x>=width || y<0 || y>=height) continue;
            const auto next=y*width+x; const auto next_point=coordinate(next);
            if (!valid(next_point) || !clear_segment(current_point,next_point,obstacles,clearance)) continue;
            const auto candidate=cost[static_cast<std::size_t>(current)]+distance(current_point,next_point);
            if (candidate+1e-10<cost[static_cast<std::size_t>(next)]) {
                cost[static_cast<std::size_t>(next)]=candidate;parent[static_cast<std::size_t>(next)]=current;
                open.emplace(candidate+distance(next_point,coordinate(goal)),next);
            }
        }
    }
    if (start!=goal && parent[static_cast<std::size_t>(goal)]<0) return {};
    std::vector<Point> reversed{to};
    for (int i=goal;i!=start;i=parent[static_cast<std::size_t>(i)]) reversed.push_back(coordinate(i));
    reversed.push_back(coordinate(start));reversed.push_back(from);
    std::reverse(reversed.begin(),reversed.end());
    std::vector<Point> path{from};std::size_t current=0;
    while (current+1<reversed.size()) {
        auto next=reversed.size()-1;
        while (next>current+1 && !clear_segment(reversed[current],reversed[next],obstacles,clearance)) --next;
        path.push_back(reversed[next]);current=next;
    }
    return path;
}

std::optional<Estimate> locate(const std::vector<Range>& ranges, double height, std::optional<Point> prior) {
    if (ranges.size()<3 || ranges.size()>16 || !std::isfinite(height)) return std::nullopt;
    if (prior && (!std::isfinite(prior->x) || !std::isfinite(prior->y))) return std::nullopt;
    std::set<std::string> identities;
    Point center{};
    for (const auto& r:ranges) {
        if (r.id.empty() || !identities.insert(r.id).second || !std::isfinite(r.x) ||
            !std::isfinite(r.y) || !std::isfinite(r.z) || !std::isfinite(r.distance) || r.distance<.05 || r.distance>200 ||
            !std::isfinite(r.sigma) || r.sigma<.01 || r.sigma>10) return std::nullopt;
        center.x+=r.x;center.y+=r.y;
    }
    center.x/=static_cast<double>(ranges.size());center.y/=static_cast<double>(ranges.size());
    auto best_cost=std::numeric_limits<double>::infinity();std::optional<Point> best;
    std::vector<std::size_t> best_inliers;
    for (std::size_t i=0;i<ranges.size();++i) for (std::size_t j=i+1;j<ranges.size();++j)
      for (std::size_t k=j+1;k<ranges.size();++k) {
        const auto solution=solve(ranges,{i,j,k},height,prior.value_or(center));
        if (!solution) continue;
        double score=0;std::vector<std::size_t> inliers;
        for (std::size_t n=0;n<ranges.size();++n) {
            const auto error=residual(*solution,ranges[n],height);
            const auto threshold=std::max(.3,3*ranges[n].sigma);
            if (error<=threshold) inliers.push_back(n);
            score+=std::min(1.0,(error/threshold)*(error/threshold));
        }
        if (prior) score+=.01*std::min(20.0,distance(*solution,*prior));
        if (inliers.size()>=3 && (inliers.size()>best_inliers.size() ||
             (inliers.size()==best_inliers.size() && score<best_cost))) {
            best=solution;best_inliers=std::move(inliers);best_cost=score;
        }
    }
    if (!best) return std::nullopt;
    const auto fitted=solve(ranges,best_inliers,height,*best);
    if (!fitted) return std::nullopt;
    Estimate result;result.position=*fitted;double a=0,b=0,d=0,squared=0;
    for (std::size_t i=0;i<ranges.size();++i) {
        const auto& r=ranges[i];
        if (std::find(best_inliers.begin(),best_inliers.end(),i)==best_inliers.end()) {result.rejected.push_back(r.id);continue;}
        result.used.push_back(r.id);
        const auto dx=fitted->x-r.x,dy=fitted->y-r.y,dz=height-r.z;
        const auto predicted=std::sqrt(dx*dx+dy*dy+dz*dz);
        if (predicted<1e-8) return std::nullopt;
        const auto w=1/(r.sigma*r.sigma);
        a+=w*dx*dx/(predicted*predicted);b+=w*dx*dy/(predicted*predicted);d+=w*dy*dy/(predicted*predicted);
        const auto error=residual(*fitted,r,height);squared+=error*error;
    }
    const auto determinant=a*d-b*b;
    if (determinant<1e-8*(a+d)*(a+d)) return std::nullopt;
    result.residual=std::sqrt(squared/static_cast<double>(best_inliers.size()));
    result.allowance=std::max(.2,3*std::sqrt((a+d)/determinant))+result.residual;
    return result;
}

LocalModel::LocalModel(const Json& j) {
    require(j.at("schema")=="mosaic.local-model.v1","model_schema");
    id_=j.at("id").get<std::string>();
    inputs_=j.at("inputs").get<std::size_t>();hidden_=j.at("hidden").get<std::size_t>();outputs_=j.at("outputs").get<std::size_t>();
    require(inputs_>0 && inputs_<=1024 && hidden_>0 && hidden_<=256 && outputs_>0 && outputs_<=32,"model_capacity");
    first_=j.at("w1").get<std::vector<double>>();first_bias_=j.at("b1").get<std::vector<double>>();
    second_=j.at("w2").get<std::vector<double>>();second_bias_=j.at("b2").get<std::vector<double>>();
    require(first_.size()==inputs_*hidden_ && first_bias_.size()==hidden_ &&
            second_.size()==hidden_*outputs_ && second_bias_.size()==outputs_,"model_shape");
    for (const auto* values:{&first_,&first_bias_,&second_,&second_bias_})
        for (auto value:*values) require(std::isfinite(value) && std::abs(value)<1000,"model_weight");
}

std::vector<double> LocalModel::infer(const std::vector<double>& input) const {
    require(input.size()==inputs_,"model_input_shape");
    for (auto value:input) require(std::isfinite(value) && value>=-10 && value<=10,"model_input_range");
    std::vector<double> hidden(hidden_),output(outputs_);
    for (std::size_t h=0;h<hidden_;++h) {
        double value=first_bias_[h];for (std::size_t i=0;i<inputs_;++i) value+=first_[h*inputs_+i]*input[i];
        hidden[h]=std::tanh(value);
    }
    for (std::size_t o=0;o<outputs_;++o) {
        double value=second_bias_[o];for (std::size_t h=0;h<hidden_;++h) value+=second_[o*hidden_+h]*hidden[h];
        output[o]=value;
    }
    const auto maximum=*std::max_element(output.begin(),output.end());double sum=0;
    for (auto& value:output) {value=std::exp(value-maximum);sum+=value;}
    for (auto& value:output) value/=sum;
    return output;
}

Json execute(const Json& request, const LocalModel* model) {
    const auto operation=request.at("op").get<std::string>();
    if (operation=="infer") {
        require(model!=nullptr,"model_not_loaded");
        const auto result=model->infer(request.at("input").get<std::vector<double>>());
        return {{"probabilities",result},{"model",model->id()}};
    }
    if (operation=="plan") {
        const auto from=point(request.at("from")),to=point(request.at("to"));
        const auto minimum=point(request.at("minimum")),maximum=point(request.at("maximum"));
        std::vector<Box> boxes;require(request.at("obstacles").size()<=1000,"obstacle_capacity");
        for (const auto& b:request.at("obstacles")) boxes.push_back({number(b.at(0),-1000,1000),number(b.at(1),-1000,1000),number(b.at(2),.01,1000),number(b.at(3),.01,1000)});
        std::optional<double> escape_clearance;
        if (request.contains("escape_clearance")) escape_clearance=number(request.at("escape_clearance"),0,3);
        const auto path=plan_path(from,to,minimum,maximum,boxes,number(request.at("cell"),.1,2),number(request.at("clearance"),0,3),escape_clearance);
        auto output=Json::array();for (const auto& p:path) output.push_back({p.x,p.y});
        return {{"path",output},{"reachable",!path.empty()}};
    }
    if (operation=="locate") {
        std::vector<Range> ranges;require(request.at("ranges").size()<=16,"range_capacity");
        for (const auto& r:request.at("ranges")) ranges.push_back({r.at("id").get<std::string>(),number(r.at("x"),-1000,1000),number(r.at("y"),-1000,1000),number(r.at("z"),-100,100),number(r.at("distance"),.05,200),number(r.at("sigma"),.01,10)});
        std::optional<Point> prior;if (request.contains("prior") && !request.at("prior").is_null()) prior=point(request.at("prior"));
        const auto result=locate(ranges,number(request.at("height"),0,10),prior);
        if (!result) return {{"position",nullptr},{"reason","insufficient_consistent_geometry"}};
        return {{"position",{result->position.x,result->position.y}},{"residual",result->residual},
            {"allowance",result->allowance},{"used",result->used},{"rejected",result->rejected}};
    }
    throw std::invalid_argument("unknown_operation");
}
} // namespace mosaic::mission
