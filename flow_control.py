from comfy_execution.graph_utils import GraphBuilder, is_link
from .tools import VariantSupport
import torch
from nodes import NODE_CLASS_MAPPINGS as ALL_NODE_CLASS_MAPPINGS

@VariantSupport()
class BatchImageLoopOpen:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "segmented_images": ("IMAGE", {"forceInput": True}),
                "segmented_masks": ("MASK", {"forceInput": True}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "iteration_count": ("INT", {"default": 0}),
            }
        }
        return inputs

    RETURN_TYPES = tuple(["FLOW_CONTROL", "IMAGE", "MASK", "INT", "INT"])
    RETURN_NAMES = tuple(["FLOW_CONTROL", "current_image", "current_mask", "max_iterations", "iteration_count"])
    FUNCTION = "while_loop_open"
    CATEGORY = "CyberEveLoop🐰"

    def while_loop_open(self, segmented_images, segmented_masks, unique_id=None, iteration_count=0):
        print(f"while_loop_open Processing iteration {iteration_count}")
        
        # 确保输入是张量
        if isinstance(segmented_images, list):
            segmented_images = torch.cat(segmented_images, dim=0)
        if isinstance(segmented_masks, list):
            segmented_masks = torch.cat(segmented_masks, dim=0)
        
        max_iterations = segmented_images.shape[0]
        if max_iterations == 0:
            raise ValueError("No images provided in segmented_images")
            
        # 获取当前迭代的图片和蒙版
        current_image = segmented_images[iteration_count:iteration_count+1]
        current_mask = segmented_masks[iteration_count:iteration_count+1]
            
        return tuple(["stub", current_image, current_mask, max_iterations, iteration_count])

@VariantSupport()
class BatchImageLoopClose:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "flow_control": ("FLOW_CONTROL", {"rawLink": True}),
                "current_image": ("IMAGE",),
                "current_mask": ("MASK",),
                "max_iterations": ("INT", {"forceInput": True}),
            },
            "hidden": {
                "dynprompt": "DYNPROMPT",
                "unique_id": "UNIQUE_ID",
                "result_images": ("IMAGE",),
                "result_masks": ("MASK",),
                "iteration_count": ("INT", {"default": 0}),
            }
        }
        return inputs

    RETURN_TYPES = tuple(["IMAGE", "MASK"])
    RETURN_NAMES = tuple(["result_images", "result_masks"])
    FUNCTION = "while_loop_close"
    CATEGORY = "CyberEveLoop🐰"

    def explore_dependencies(self, node_id, dynprompt, upstream, parent_ids):
        node_info = dynprompt.get_node(node_id)
        if "inputs" not in node_info:
            return

        for k, v in node_info["inputs"].items():
            if is_link(v):
                parent_id = v[0]
                display_id = dynprompt.get_display_node_id(parent_id)
                display_node = dynprompt.get_node(display_id)
                class_type = display_node["class_type"]
                # 排除循环结束节点
                if class_type not in ['BatchImageLoopClose']:
                    parent_ids.append(display_id)
                if parent_id not in upstream:
                    upstream[parent_id] = []
                    self.explore_dependencies(parent_id, dynprompt, upstream, parent_ids)
                upstream[parent_id].append(node_id)

    def explore_output_nodes(self, dynprompt, upstream, output_nodes, parent_ids):
        """探索并添加输出节点的连接"""
        for parent_id in upstream:
            display_id = dynprompt.get_display_node_id(parent_id)
            for output_id in output_nodes:
                id = output_nodes[output_id][0]
                if id in parent_ids and display_id == id and output_id not in upstream[parent_id]:
                    if '.' in parent_id:
                        arr = parent_id.split('.')
                        arr[len(arr)-1] = output_id
                        upstream[parent_id].append('.'.join(arr))
                    else:
                        upstream[parent_id].append(output_id)

    def collect_contained(self, node_id, upstream, contained):
        if node_id not in upstream:
            return
        for child_id in upstream[node_id]:
            if child_id not in contained:
                contained[child_id] = True
                self.collect_contained(child_id, upstream, contained)

    def while_loop_close(self, flow_control, current_image, current_mask, max_iterations, 
                        iteration_count=0, result_images=None, result_masks=None,
                        dynprompt=None, unique_id=None,):
        print(f"Iteration {iteration_count} of {max_iterations}")
        
        # 维度处理
        if len(current_image.shape) == 3:
            current_image = current_image.unsqueeze(0)
        if len(current_mask.shape) == 2:
            current_mask = current_mask.unsqueeze(0)

        # 结果初始化
        if result_images is None:
            result_images = torch.zeros((max_iterations,) + current_image.shape[1:],
                                     dtype=current_image.dtype,
                                     device=current_image.device)
            result_masks = torch.zeros((max_iterations,) + current_mask.shape[1:],
                                    dtype=current_mask.dtype,
                                    device=current_mask.device)
            
        # 存储当前结果
        result_images[iteration_count:iteration_count+1] = current_image
        result_masks[iteration_count:iteration_count+1] = current_mask

        # 检查是否继续循环
        if iteration_count >= max_iterations - 1:
            print(f"Loop finished with {iteration_count + 1} iterations")
            return (result_images, result_masks)

        # 准备下一次循环
        this_node = dynprompt.get_node(unique_id)
        upstream = {}
        parent_ids = []
        self.explore_dependencies(unique_id, dynprompt, upstream, parent_ids)
        parent_ids = list(set(parent_ids))  # 去重

        # 获取并处理输出节点
        prompts = dynprompt.get_original_prompt()
        output_nodes = {}
        for id in prompts:
            node = prompts[id]
            if "inputs" not in node:
                continue
            class_type = node["class_type"]
            if class_type in ALL_NODE_CLASS_MAPPINGS:
                class_def = ALL_NODE_CLASS_MAPPINGS[class_type]
                if hasattr(class_def, 'OUTPUT_NODE') and class_def.OUTPUT_NODE == True:
                    for k, v in node['inputs'].items():
                        if is_link(v):
                            output_nodes[id] = v

        # 创建新图
        graph = GraphBuilder()
        self.explore_output_nodes(dynprompt, upstream, output_nodes, parent_ids)
        
        contained = {}
        open_node = flow_control[0]
        self.collect_contained(open_node, upstream, contained)
        contained[unique_id] = True
        contained[open_node] = True

        # 创建节点
        for node_id in contained:
            original_node = dynprompt.get_node(node_id)
            node = graph.node(original_node["class_type"], 
                            "Recurse" if node_id == unique_id else node_id)
            node.set_override_display_id(node_id)
            
        # 设置连接
        for node_id in contained:
            original_node = dynprompt.get_node(node_id)
            node = graph.lookup_node("Recurse" if node_id == unique_id else node_id)
            for k, v in original_node["inputs"].items():
                if is_link(v) and v[0] in contained:
                    parent = graph.lookup_node(v[0])
                    node.set_input(k, parent.out(v[1]))
                else:
                    node.set_input(k, v)

        # 设置节点参数
        my_clone = graph.lookup_node("Recurse")
        my_clone.set_input("iteration_count", iteration_count + 1)
        my_clone.set_input("result_images", result_images)
        my_clone.set_input("result_masks", result_masks)
        
        new_open = graph.lookup_node(open_node)
        new_open.set_input("iteration_count", iteration_count + 1)

        print(f"Continuing to iteration {iteration_count + 1}")

        return {
            "result": tuple([my_clone.out(0), my_clone.out(1)]),
            "expand": graph.finalize(),
        }


@VariantSupport()
class SingleImageLoopOpen:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "image": ("IMAGE",),
                "max_iterations": ("INT", {"default": 5, "min": 1, "max": 100}),
            },
            "optional": {
                "mask": ("MASK",),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "iteration_count": ("INT", {"default": 0}),
                "previous_image": ("IMAGE",),
                "previous_mask": ("MASK",),
            }
        }
        return inputs

    RETURN_TYPES = tuple(["FLOW_CONTROL", "IMAGE", "MASK", "INT", "INT"])
    RETURN_NAMES = tuple(["FLOW_CONTROL", "current_image", "current_mask", "max_iterations", "iteration_count"])
    FUNCTION = "loop_open"
    CATEGORY = "CyberEveLoop🐰"

    def loop_open(self, image, max_iterations, mask=None, unique_id=None, 
                 iteration_count=0, previous_image=None, previous_mask=None):
        print(f"SingleImageLoopOpen Processing iteration {iteration_count}")
        
        # 确保维度正确
        if len(image.shape) == 3:
            image = image.unsqueeze(0)
        if mask is not None and len(mask.shape) == 2:
            mask = mask.unsqueeze(0)
            
        # 使用上一次循环的结果（如果有）
        current_image = previous_image if previous_image is not None and iteration_count > 0 else image
        current_mask = previous_mask if previous_mask is not None and iteration_count > 0 else mask
            
        return tuple(["stub", current_image, current_mask, max_iterations, iteration_count])

@VariantSupport()
class SingleImageLoopClose:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "flow_control": ("FLOW_CONTROL", {"rawLink": True}),
                "current_image": ("IMAGE",),
                "max_iterations": ("INT", {"forceInput": True}),
            },
            "optional": {
                "current_mask": ("MASK",),
            },
            "hidden": {
                "dynprompt": "DYNPROMPT",
                "unique_id": "UNIQUE_ID",
                "iteration_count": ("INT", {"default": 0}),
            }
        }
        return inputs

    RETURN_TYPES = tuple(["IMAGE", "MASK"])
    RETURN_NAMES = tuple(["final_image", "final_mask"])
    FUNCTION = "loop_close"
    CATEGORY = "CyberEveLoop🐰"

    def explore_dependencies(self, node_id, dynprompt, upstream, parent_ids):
        node_info = dynprompt.get_node(node_id)
        if "inputs" not in node_info:
            return

        for k, v in node_info["inputs"].items():
            if is_link(v):
                parent_id = v[0]
                display_id = dynprompt.get_display_node_id(parent_id)
                display_node = dynprompt.get_node(display_id)
                class_type = display_node["class_type"]
                if class_type not in ['SingleImageLoopClose']:
                    parent_ids.append(display_id)
                if parent_id not in upstream:
                    upstream[parent_id] = []
                    self.explore_dependencies(parent_id, dynprompt, upstream, parent_ids)
                upstream[parent_id].append(node_id)

    def explore_output_nodes(self, dynprompt, upstream, output_nodes, parent_ids):
        for parent_id in upstream:
            display_id = dynprompt.get_display_node_id(parent_id)
            for output_id in output_nodes:
                id = output_nodes[output_id][0]
                if id in parent_ids and display_id == id and output_id not in upstream[parent_id]:
                    if '.' in parent_id:
                        arr = parent_id.split('.')
                        arr[len(arr)-1] = output_id
                        upstream[parent_id].append('.'.join(arr))
                    else:
                        upstream[parent_id].append(output_id)

    def collect_contained(self, node_id, upstream, contained):
        if node_id not in upstream:
            return
        for child_id in upstream[node_id]:
            if child_id not in contained:
                contained[child_id] = True
                self.collect_contained(child_id, upstream, contained)

    def loop_close(self, flow_control, current_image, max_iterations, current_mask=None,
                  iteration_count=0, dynprompt=None, unique_id=None):
        print(f"Iteration {iteration_count} of {max_iterations}")
        
        # 维度处理
        if len(current_image.shape) == 3:
            current_image = current_image.unsqueeze(0)
        if current_mask is not None and len(current_mask.shape) == 2:
            current_mask = current_mask.unsqueeze(0)

        # 检查是否继续循环
        if iteration_count >= max_iterations - 1:
            print(f"Loop finished with {iteration_count + 1} iterations")
            return (current_image, current_mask if current_mask is not None else torch.zeros_like(current_image[:,:,:,0]))

        # 准备下一次循环
        this_node = dynprompt.get_node(unique_id)
        upstream = {}
        parent_ids = []
        self.explore_dependencies(unique_id, dynprompt, upstream, parent_ids)
        parent_ids = list(set(parent_ids))

        # 获取并处理输出节点
        prompts = dynprompt.get_original_prompt()
        output_nodes = {}
        for id in prompts:
            node = prompts[id]
            if "inputs" not in node:
                continue
            class_type = node["class_type"]
            if class_type in ALL_NODE_CLASS_MAPPINGS:
                class_def = ALL_NODE_CLASS_MAPPINGS[class_type]
                if hasattr(class_def, 'OUTPUT_NODE') and class_def.OUTPUT_NODE == True:
                    for k, v in node['inputs'].items():
                        if is_link(v):
                            output_nodes[id] = v

        # 创建新图
        graph = GraphBuilder()
        self.explore_output_nodes(dynprompt, upstream, output_nodes, parent_ids)
        
        contained = {}
        open_node = flow_control[0]
        self.collect_contained(open_node, upstream, contained)
        contained[unique_id] = True
        contained[open_node] = True

        # 创建节点
        for node_id in contained:
            original_node = dynprompt.get_node(node_id)
            node = graph.node(original_node["class_type"], 
                            "Recurse" if node_id == unique_id else node_id)
            node.set_override_display_id(node_id)
            
        # 设置连接
        for node_id in contained:
            original_node = dynprompt.get_node(node_id)
            node = graph.lookup_node("Recurse" if node_id == unique_id else node_id)
            for k, v in original_node["inputs"].items():
                if is_link(v) and v[0] in contained:
                    parent = graph.lookup_node(v[0])
                    node.set_input(k, parent.out(v[1]))
                else:
                    node.set_input(k, v)

        # 设置节点参数
        my_clone = graph.lookup_node("Recurse")
        my_clone.set_input("iteration_count", iteration_count + 1)
        
        new_open = graph.lookup_node(open_node)
        new_open.set_input("iteration_count", iteration_count + 1)
        new_open.set_input("previous_image", current_image)
        if current_mask is not None:
            new_open.set_input("previous_mask", current_mask)

        print(f"Continuing to iteration {iteration_count + 1}")

        return {
            "result": tuple([my_clone.out(0), my_clone.out(1)]),
            "expand": graph.finalize(),
        }
    


@VariantSupport()
class LoopIndexSwitch:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        """
        预定义100个隐藏的lazy输入
        """
        optional_inputs = {
            "default_value": ("*", {"lazy": True}),  # 默认值也设为lazy
        }
        # 添加100个隐藏的lazy输入
        hidden_inputs = {}
        for i in range(100):
            hidden_inputs[f"while_{i}"] = ("*", {"lazy": True})
            
        return {
            "required": {
                "iteration_count": ("INT", {"forceInput": True}),  # 当前迭代次数
            },
            "optional": optional_inputs,
            "hidden": hidden_inputs,
        }

    RETURN_TYPES = ("*",)
    FUNCTION = "index_switch"
    CATEGORY = "CyberEveLoop🐰"

    def check_lazy_status(self, iteration_count, **kwargs):
        """
        检查当前迭代需要的输入和默认值
        """
        needed = []
        current_key = f"while_{iteration_count}"

        # 检查当前迭代的输入
        if current_key in kwargs :
            needed.append(current_key)
        else:
            needed.append("default_value")

        print(f"Index switch needed: {needed}")
        return needed



    def index_switch(self, iteration_count, **kwargs):
        """
        根据当前迭代次数选择对应的输入值
        """
        current_key = f"while_{iteration_count}"
        
        if current_key in kwargs and kwargs[current_key] is not None:
            return (kwargs[current_key],)
        return (kwargs.get("default_value"),)


CyberEve_Loop_CLASS_MAPPINGS = {
    "CyberEve_BatchImageLoopOpen": BatchImageLoopOpen,
    "CyberEve_BatchImageLoopClose": BatchImageLoopClose,
    "CyberEve_LoopIndexSwitch": LoopIndexSwitch,
    "CyberEve_SingleImageLoopOpen": SingleImageLoopOpen,
    "CyberEve_SingleImageLoopClose": SingleImageLoopClose,
}

CyberEve_Loop_DISPLAY_NAME_MAPPINGS = {
    "CyberEve_BatchImageLoopOpen": "Batch Image Loop Open🐰",
    "CyberEve_BatchImageLoopClose": "Batch Image Loop Close🐰",
    "CyberEve_LoopIndexSwitch": "Loop Index Switch🐰",
    "CyberEve_SingleImageLoopOpen": "Single Image Loop Open🐰",
    "CyberEve_SingleImageLoopClose": "Single Image Loop Close🐰",
}