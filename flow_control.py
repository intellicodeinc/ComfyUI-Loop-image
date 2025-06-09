from comfy_execution.graph_utils import GraphBuilder, is_link
from .tools import VariantSupport
import torch.nn.functional as F
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
                "previous_image": ("IMAGE",),  # 新增：接收上一次循环的图片
            }
        }
        return inputs

    RETURN_TYPES = tuple(["FLOW_CONTROL", "IMAGE", "MASK", "INT", "INT"])
    RETURN_NAMES = tuple(["FLOW_CONTROL", "current_image", "current_mask", "max_iterations", "iteration_count"])
    FUNCTION = "while_loop_open"
    CATEGORY = "CyberEveLoop🐰"

    def standardize_input(self, images, masks):
        """
        标准化输入格式
        images: 确保是4D tensor [B,H,W,C]
        masks: 确保是3D tensor [B,H,W]
        如果images是单张图片，会扩展到与masks相同的批次大小
        """
        # 处理masks（先处理masks以获取批次大小）
        if isinstance(masks, list):
            masks = torch.cat(masks, dim=0)
        if len(masks.shape) == 2:  # [H,W] -> [1,H,W]
            masks = masks.unsqueeze(0)
        assert len(masks.shape) == 3, f"Masks must be 3D [B,H,W], got shape {masks.shape}"
        
        # 处理images
        if isinstance(images, list):
            images = torch.cat(images, dim=0)
        if len(images.shape) == 3:  # [H,W,C] -> [1,H,W,C]
            images = images.unsqueeze(0)
        assert len(images.shape) == 4, f"Images must be 4D [B,H,W,C], got shape {images.shape}"

        # 检查是否需要扩展images
        if images.shape[0] == 1 and masks.shape[0] > 1:
            print(f"Expanding single image to match mask batch size: {masks.shape[0]}")
            images = images.expand(masks.shape[0], -1, -1, -1)
        
        # 确保batch维度相同
        assert images.shape[0] == masks.shape[0], \
            f"Batch size mismatch: images {images.shape[0]} vs masks {masks.shape[0]}"

        return images, masks


    def resize_to_match(self, image, target_shape):
        """调整图片尺寸以匹配目标shape"""
        if image.shape[1:3] != target_shape[1:3]:
            # 确保是4D tensor
            if len(image.shape) == 3:
                image = image.unsqueeze(0)
            
            # 转换为[B,C,H,W]用于插值
            image = image.permute(0, 3, 1, 2)
            
            # 执行resize
            image = F.interpolate(
                image,
                size=(target_shape[1], target_shape[2]),
                mode='bilinear',
                align_corners=False
            )
            
            # 转换回[B,H,W,C]
            image = image.permute(0, 2, 3, 1)
        
        return image

    def while_loop_open(self, segmented_images, segmented_masks, unique_id=None, 
                       iteration_count=0, previous_image=None):
        print(f"while_loop_open Processing iteration {iteration_count}")
        
        # 标准化输入
        segmented_images, segmented_masks = self.standardize_input(segmented_images, segmented_masks)
        
        # 获取最大迭代次数
        max_iterations = segmented_images.shape[0]
        if max_iterations == 0:
            raise ValueError("No images provided in segmented_images")
            
        # 验证迭代计数
        if iteration_count >= max_iterations:
            raise ValueError(f"Iteration count {iteration_count} exceeds max iterations {max_iterations}")
            
        # 处理上一次循环传回的图片
        if previous_image is not None and iteration_count > 0:
            # 确保previous_image维度正确
            if len(previous_image.shape) == 3:
                previous_image = previous_image.unsqueeze(0)
                
            # 调整尺寸以匹配batch中的图片
            previous_image = self.resize_to_match(previous_image, segmented_images.shape)
            
            # 替换下一次要处理的图片
            next_idx = min(iteration_count, max_iterations - 1)
            segmented_images[next_idx:next_idx+1] = previous_image
            
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
            "optional": {
                "pass_back": ("BOOLEAN", {"default": False}),  # 新增：控制是否传回图片
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

    def standardize_input(self, image, mask):
        """
        标准化输入格式
        image: 确保是4D tensor [B,H,W,C]
        mask: 确保是3D tensor [B,H,W]
        """
        # 处理image
        if len(image.shape) == 3:  # [H,W,C] -> [1,H,W,C]
            image = image.unsqueeze(0)
        assert len(image.shape) == 4, f"Image must be 4D [B,H,W,C], got shape {image.shape}"

        # 处理mask
        if len(mask.shape) == 2:  # [H,W] -> [1,H,W]
            mask = mask.unsqueeze(0)
        assert len(mask.shape) == 3, f"Mask must be 3D [B,H,W], got shape {mask.shape}"

        return image, mask

    def initialize_results(self, max_iterations, current_image, current_mask):
        """
        初始化结果张量，确保与MaskSplit输出格式一致
        """
        # 确保维度正确
        assert len(current_image.shape) == 4, "Current image must be 4D [B,H,W,C]"
        assert len(current_mask.shape) == 3, "Current mask must be 3D [B,H,W]"

        # 创建结果张量，确保格式一致
        result_images = torch.zeros(
            (max_iterations, current_image.shape[1], current_image.shape[2], current_image.shape[3]),
            dtype=current_image.dtype,
            device=current_image.device
        )  # 明确指定 [B,H,W,C]

        result_masks = torch.zeros(
            (max_iterations, current_mask.shape[1], current_mask.shape[2]),
            dtype=current_mask.dtype,
            device=current_mask.device
        )  # 明确指定 [B,H,W]
        
        return result_images, result_masks

    def while_loop_close(self, flow_control, current_image, current_mask, max_iterations, 
                        pass_back=False, iteration_count=0, result_images=None, result_masks=None,
                        dynprompt=None, unique_id=None,):
        print(f"Iteration {iteration_count} of {max_iterations}")
        
        # 标准化输入，确保格式一致
        current_image, current_mask = self.standardize_input(current_image, current_mask)

        # 验证迭代计数
        if iteration_count >= max_iterations:
            raise ValueError(f"Iteration count {iteration_count} exceeds max iterations {max_iterations}")

        # 结果初始化或验证
        if result_images is None or result_masks is None:
            result_images, result_masks = self.initialize_results(max_iterations, current_image, current_mask)
        else:
            # 验证现有结果的维度和格式
            assert result_images.shape[0] == max_iterations and len(result_images.shape) == 4, \
                f"Result images must be 4D [B,H,W,C] with batch size {max_iterations}"
            assert result_masks.shape[0] == max_iterations and len(result_masks.shape) == 3, \
                f"Result masks must be 3D [B,H,W] with batch size {max_iterations}"
            
        # 存储当前结果
        result_images[iteration_count:iteration_count+1] = current_image
        result_masks[iteration_count:iteration_count+1] = current_mask
        
        # 检查是否继续循环
        if iteration_count == max_iterations - 1:
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
        if pass_back:  # 新增：根据pass_back决定是否传回图片
            new_open.set_input("previous_image", current_image)

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

"""
- LoopReduceOpen
- LoopReduceClose

Author: Wonbim Kim
Created At: 2025-06-05
Email: wbkim@intellicode.co.kr
"""
@VariantSupport()
class LoopReduceOpen:
    
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "input_size": ("INT", {"default": 5, "min": 1, "max": 100}),
            },
            "optional": {
                "initial": ("LIST",),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "iteration_count": ("INT", {"default": 0}),
                "previous_list": ("LIST",),
            }
        }
        return inputs
    
    RETURN_TYPES = tuple(["FLOW_CONTROL", "LIST", "INT", "INT"])
    RETURN_NAMES = tuple(["FLOW_CONTROL", "current_list", "input_size", "iteration_count"])
    FUNCTION = "loop_open"
    CATEGORY = "Intellicode/loop_control"
    
    @classmethod
    def _loop_open(cls, input_size, initial=None, unique_id=None, 
                 iteration_count=0, previous_list=None):
        
        print(f"{cls.__class__.__name__} Processing iteration {iteration_count}")
                
        initial = [] if initial is None else initial
        
        current_list = initial[:] if previous_list is None else previous_list
        
        return tuple(["stub", current_list, input_size, iteration_count])

    
    
    def loop_open(self, input_size, initial=None, unique_id=None, 
                 iteration_count=0, previous_list=None):
        return self._loop_open(input_size, initial, unique_id, iteration_count, previous_list)

@VariantSupport()
class AppendList:
    def __init__(self):
        pass
    
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required" : {
                "current_list" : ("LIST",),
                "current_value" : ("*"), # TODO : get any value
            }
        }
        return inputs
    
    RETURN_TYPES = tuple(["LIST"])
    RETURN_NAMES = tuple(["current_list"])
    FUNCTION = "appending"
    CATEGORY = "Intellicode/loop_control"
    
    def appending(self, current_list, current_value):
        
        current_list.append(current_value)
        return tuple([current_list])
    

class LoopReduceClose(SingleImageLoopClose):
    
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "flow_control" : ("FLOW_CONTROL", {"rawLink" : True}),
                "current_list" : ("LIST",),
                "input_size" : ("INT", {"forceInput" : True}),
            },
            "hidden" : {
                "dynprompt" : "DYNPROMPT",
                "unique_id" : "UNIQUE_ID",
                "iteration_count" : ("INT", {"default":0}),
            }
        }
        return inputs

    RETURN_TYPES = tuple(["LIST"])
    RETURN_NAME = tuple(["final_list"])
    FUNCTION = "loop_close"
    CATEGORY = "Intellicode/loop_control"

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
                if class_type not in ['LoopReduceClose']:
                    parent_ids.append(display_id)
                if parent_id not in upstream:
                    upstream[parent_id] = []
                    self.explore_dependencies(parent_id, dynprompt, upstream, parent_ids)
                upstream[parent_id].append(node_id)

    def loop_close(self, flow_control, current_list, input_size,
                  iteration_count=0, dynprompt=None, unique_id=None):
        print(f"Iteration {iteration_count} of {input_size}")

        # Loop End
        if iteration_count >= input_size - 1:
            print(f"Loop finished with {iteration_count + 1} iterations")
            return (current_list[-input_size:],)
        
        # prepare next iteration
        this_node = dynprompt.get_node(unique_id)
        upstream = {}
        parent_ids = []
        self.explore_dependencies(unique_id, dynprompt, upstream, parent_ids)
        parent_ids = list(set(parent_ids))

        # Getting and processing output nodes
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

        # Creating a New Diagram
        graph = GraphBuilder()
        self.explore_output_nodes(dynprompt, upstream, output_nodes, parent_ids) ###
        
        contained = {}
        open_node = flow_control[0]
        self.collect_contained(open_node, upstream, contained)
        contained[unique_id] = True
        contained[open_node] = True

        # Create a node
        for node_id in contained:
            original_node = dynprompt.get_node(node_id)
            node = graph.node(original_node["class_type"], 
                            "Recurse" if node_id == unique_id else node_id)
            node.set_override_display_id(node_id)
            
        # Setting up the connection
        for node_id in contained:
            original_node = dynprompt.get_node(node_id)
            node = graph.lookup_node("Recurse" if node_id == unique_id else node_id)
            for k, v in original_node["inputs"].items():
                if is_link(v) and v[0] in contained:
                    parent = graph.lookup_node(v[0])
                    node.set_input(k, parent.out(v[1]))
                else:
                    node.set_input(k, v)

        # Setting Node Parameters
        my_clone = graph.lookup_node("Recurse")
        my_clone.set_input("iteration_count", iteration_count + 1)
        
        new_open = graph.lookup_node(open_node)
        new_open.set_input("iteration_count", iteration_count + 1)
        new_open.set_input("previous_list", current_list)

        print(f"Continuing to iteration {iteration_count + 1}")

        return {
            "result": tuple([my_clone.out(0)[-input_size:]]),
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
Intellicode_CLASS_MAPPINGS = {
    "LoopReduceClose" : LoopReduceClose,
    "LoopReduceOpen" : LoopReduceOpen,
    "AppendList" : AppendList,
}
Intellicode_DISPLAY_NAME_MAPPINGS = {
    "LoopReduceOpen" : "Loop like Reduce function Open",
    "LoopReduceClose" : "Loop like Reduce function Close",
    "AppendList" : "Append values to List"
}